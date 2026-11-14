"""Web server: accepts a YouTube link, runs the clipping pipeline in the
background, and serves progress and finished clips to the page."""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import traceback
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import config, render, selector, source

app = FastAPI(title="Clipsmith")

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1)  # one video at a time; encoding uses every core

_YT = re.compile(r"^https?://([\w-]+\.)?(youtube\.com|youtu\.be)/", re.I)


class JobRequest(BaseModel):
    url: str
    clip_count: int = Field(default=5, ge=1, le=15)
    min_len: int = Field(default=30, ge=10, le=170)
    max_len: int = Field(default=60, ge=15, le=180)
    style: str = "yellow"
    layout: str = "auto"
    hook: bool = True


def _job_dir(job_id: str) -> Path:
    return config.JOBS_DIR / job_id


def _save(job: dict) -> None:
    d = _job_dir(job["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "job.json")


def _update(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs[job_id]
        job.update(fields)
        _save(job)


def _load_existing() -> None:
    for f in config.JOBS_DIR.glob("*/job.json"):
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if job.get("status") in ("queued", "running"):
            job["status"] = "error"
            job["error"] = "The app was closed while this was processing."
        _jobs[job["id"]] = job


_load_existing()


def _run(job_id: str, req: JobRequest) -> None:
    workdir = _job_dir(job_id)

    last = {"pct": -1.0, "msg": ""}

    def progress(pct: float, message: str) -> None:
        pct = round(min(pct, 99), 1)
        # the download hook fires many times a second; don't rewrite job.json each time
        if message == last["msg"] and abs(pct - last["pct"]) < 1:
            return
        last.update(pct=pct, msg=message)
        _update(job_id, progress=pct, message=message)

    try:
        _update(job_id, status="running")
        upload = _jobs[job_id].get("upload")
        if upload:
            path = next(workdir.glob("source.*"))
            src = source.from_local_file(path, workdir, progress, title=Path(upload).stem)
        else:
            src = source.download(req.url, workdir, progress)
        _update(job_id, title=src.title, duration=src.duration, transcript_source=src.transcript_source)

        progress(42, "Finding the best moments")
        sentences = selector.to_sentences(src.words)
        clips, method, warning = selector.select(
            sentences, src.title, req.clip_count, req.min_len, req.max_len, progress
        )
        if not clips:
            raise RuntimeError(
                f"No stretch of speech between {req.min_len} and {req.max_len} seconds was found in this video."
            )
        _update(job_id, selection=method, warning=warning)

        done: list[dict] = []
        for i, clip in enumerate(clips):
            progress(45 + 54 * i / len(clips), f"Rendering clip {i + 1} of {len(clips)}")
            # Let the moment land: run on into the pause after the last word
            # (a laugh, a reaction, engine noise) instead of cutting right after it.
            start = max(0.0, clip.start - 0.15)
            next_word = next((w.start for w in src.words if w.start >= clip.end - 0.05), None)
            tail = 1.5 if next_word is None else max(0.3, min(1.5, next_word - clip.end - 0.1))
            end = min(src.duration or clip.end + tail, clip.end + tail)
            name = f"clip_{i + 1:02d}"
            info = render.render_clip(
                src.video_path, src.words, start, end, workdir, name,
                style=req.style, layout=req.layout, hook=clip.hook if req.hook else None,
            )
            done.append(
                asdict(clip)
                | {
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "length": round(end - start, 1),
                    "video": f"/media/{job_id}/{name}.mp4",
                    "thumb": f"/media/{job_id}/{name}.jpg",
                    "layout": info["layout"],
                }
            )
            _update(job_id, clips=list(done))

        src.video_path.unlink(missing_ok=True)  # the source is large; clips are what matter
        for leftover in workdir.glob("source.*"):
            leftover.unlink(missing_ok=True)
        _update(job_id, status="done", progress=100, message="Done")
    except Exception as exc:
        traceback.print_exc()
        msg = str(exc).replace("ERROR: ", "").strip() or type(exc).__name__
        _update(job_id, status="error", error=msg[:500])


@app.get("/api/status")
def status() -> dict:
    return {
        "ai": config.ai_provider(),
        "missing": config.missing_tools(),
        "model": {
            "gemini": config.GEMINI_MODEL,
            "claude": config.CLAUDE_MODEL,
            "ollama": f"{config.OLLAMA_MODEL} (local)",
        }.get(config.ai_provider()),
        "styles": {k: v["label"] for k, v in render.STYLES.items()},
    }


def _check_options(req: JobRequest) -> None:
    if req.min_len >= req.max_len:
        raise HTTPException(400, "Minimum length must be shorter than maximum length.")
    if req.style not in render.STYLES:
        raise HTTPException(400, "Unknown caption style.")
    if req.layout not in ("auto", "fill", "fit"):
        raise HTTPException(400, "Unknown layout.")


def _new_job(req: JobRequest, job_id: str | None = None, **extra) -> dict:
    job_id = job_id or uuid.uuid4().hex[:10]
    job = {
        "id": job_id, "url": req.url.strip(), "status": "queued", "progress": 0, "message": "Waiting to start",
        "title": None, "clips": [], "error": None, "warning": None, "selection": None,
        "created": time.time(), "options": req.model_dump(exclude={"url"}),
    } | extra
    with _lock:
        _jobs[job_id] = job
        _save(job)
    _pool.submit(_run, job_id, req)
    return job


@app.post("/api/jobs")
def create_job(req: JobRequest) -> dict:
    if not _YT.match(req.url.strip()):
        raise HTTPException(400, "That doesn't look like a YouTube link.")
    _check_options(req)
    return _new_job(req)


_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}


@app.post("/api/jobs/upload")
async def upload_job(
    file: UploadFile = File(...),
    clip_count: int = Form(5),
    min_len: int = Form(30),
    max_len: int = Form(60),
    style: str = Form("yellow"),
    layout: str = Form("auto"),
    hook: bool = Form(True),
) -> dict:
    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in _VIDEO_EXTS:
        raise HTTPException(400, "Please upload a video file: mp4, mov, mkv or webm.")
    try:
        req = JobRequest(url="", clip_count=clip_count, min_len=min_len, max_len=max_len,
                         style=style, layout=layout, hook=hook)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    _check_options(req)
    job_id = uuid.uuid4().hex[:10]
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    try:
        with open(d / f"source{ext}", "wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return _new_job(req, job_id, upload=name)


@app.get("/api/jobs/{job_id}/zip")
def download_zip(job_id: str) -> FileResponse:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    d = _job_dir(job_id)
    files = [d / Path(c["video"]).name for c in job.get("clips") or []]
    files = [f for f in files if f.is_file()]
    if not files:
        raise HTTPException(409, "This video has no finished clips yet.")
    zpath = d / "clips.zip"
    tmp = d / "clips.zip.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(f, f.name)
    tmp.replace(zpath)
    title = re.sub(r'[\\/:*?"<>|]+', "", job.get("title") or "clips").strip()[:80] or "clips"
    return FileResponse(zpath, media_type="application/zip", filename=f"{title}.zip")


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    with _lock:
        return sorted(_jobs.values(), key=lambda j: -j["created"])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found.")
        if job["status"] in ("queued", "running"):
            raise HTTPException(409, "This video is still processing.")
        del _jobs[job_id]
    shutil.rmtree(_job_dir(job_id), ignore_errors=True)
    return {"ok": True}


app.mount("/media", StaticFiles(directory=config.JOBS_DIR), name="media")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")
