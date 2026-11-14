import io
import shutil
import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import main, source
from app.source import Word


@pytest.fixture
def client(monkeypatch):
    submitted = []
    monkeypatch.setattr(main._pool, "submit", lambda fn, *a: submitted.append(a))  # never run the pipeline
    monkeypatch.setattr(main, "_jobs", {})
    c = TestClient(main.app)
    c.submitted = submitted
    return c


def _upload(client, name="My Talk.mp4", data=b"fake video bytes", **fields):
    return client.post("/api/jobs/upload", files={"file": (name, io.BytesIO(data), "video/mp4")}, data=fields)


def test_upload_is_queued_and_saved(client):
    res = _upload(client, clip_count="3", style="yellow")
    assert res.status_code == 200
    job = res.json()
    assert job["status"] == "queued" and job["upload"] == "My Talk.mp4"
    assert job["options"]["clip_count"] == 3
    assert len(client.submitted) == 1
    saved = main._job_dir(job["id"]) / "source.mp4"
    assert saved.read_bytes() == b"fake video bytes"


@pytest.mark.parametrize("name", ["notes.txt", "video", "clip.avi"])
def test_upload_rejects_bad_extension(client, name):
    res = _upload(client, name=name)
    assert res.status_code == 400
    assert "mp4" in res.json()["detail"]
    assert client.submitted == []


def test_upload_rejects_bad_options(client):
    res = _upload(client, min_len="60", max_len="30")
    assert res.status_code == 400
    assert client.submitted == []


def _finished_job(client, clips=2):
    job = _upload(client).json()
    d = main._job_dir(job["id"])
    entries = []
    for i in range(clips):
        name = f"clip_{i + 1:02d}"
        (d / f"{name}.mp4").write_bytes(f"video {i}".encode())
        entries.append({"video": f"/media/{job['id']}/{name}.mp4", "title": f"Clip {i}"})
    main._jobs[job["id"]].update(status="done", clips=entries, title="Great Talk: Part 1")
    return job["id"]


def test_zip_contains_all_clips(client):
    job_id = _finished_job(client)
    res = client.get(f"/api/jobs/{job_id}/zip")
    assert res.status_code == 200
    assert "Great Talk" in res.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert sorted(z.namelist()) == ["clip_01.mp4", "clip_02.mp4"]
        assert z.read("clip_02.mp4") == b"video 1"
        assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())


def test_zip_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope/zip").status_code == 404


def test_zip_without_clips_is_409(client):
    job_id = _finished_job(client, clips=0)
    assert client.get(f"/api/jobs/{job_id}/zip").status_code == 409


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs ffmpeg")
def test_from_local_file(tmp_path, monkeypatch):
    video = tmp_path / "Holiday Trip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240",
         "-f", "lavfi", "-i", "sine=duration=2", "-shortest", str(video)],
        check=True,
    )
    monkeypatch.setattr(source, "whisper_transcribe", lambda p, w, prog: [Word("hello", 0.1, 0.5)])
    src = source.from_local_file(video, tmp_path, lambda *a: None)
    assert src.title == "Holiday Trip"
    assert 1.5 < src.duration < 2.6
    assert src.transcript_source == "whisper"
    assert src.words[0].text == "hello"
    assert src.video_path == video
