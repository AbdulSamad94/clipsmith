"""Turn a time range of the source video into a finished vertical clip:
reframe to 9:16 around the speaker, burn in animated captions, encode."""
from __future__ import annotations

import statistics
import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import config
from .source import Word

W, H = config.OUT_W, config.OUT_H

# ASS colours are &HBBGGRR&
STYLES = {
    "yellow": {"label": "Bold Yellow", "font": "Arial Black", "size": 92, "active": "&H00F6FF&", "upper": True},
    "green": {"label": "Green Pop", "font": "Arial Black", "size": 92, "active": "&H5CFF4D&", "upper": True},
    "clean": {"label": "Clean White", "font": "Arial", "size": 84, "active": "&HFFD27A&", "upper": False},
}


# ---------- reframing ----------

def track_faces(video: Path, start: float, end: float, fps: float = 3.0) -> list[tuple[float, float | None]]:
    """Sample the clip and return (time_in_clip, face_centre_x as 0..1 or None)."""
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    src_w, src_h = _probe_size(video)
    fw_px = 480
    fh_px = int(src_h * fw_px / src_w) // 2 * 2
    # One ffmpeg pass piping small grey frames is far faster than seeking per sample.
    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video),
         "-an", "-vf", f"fps={fps},scale={fw_px}:{fh_px}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    samples: list[tuple[float, float | None]] = []
    frame_bytes = fw_px * fh_px
    i = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            img = np.frombuffer(buf, dtype=np.uint8).reshape(fh_px, fw_px)
            faces = cascade.detectMultiScale(img, scaleFactor=1.15, minNeighbors=6, minSize=(36, 36))
            # a face under ~7% of frame width is a wide shot (stage, audience);
            # following it gives a jumpy crop with the speaker at the edge
            faces = [f for f in faces if f[2] >= 0.07 * fw_px]
            if len(faces):
                x, _, fw, _ = max(faces, key=lambda f: f[2] * f[3])
                samples.append((i / fps, (x + fw / 2) / fw_px))
            else:
                samples.append((i / fps, None))
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()
    return samples


def camera_path(samples: list[tuple[float, float | None]], deadzone: float = 0.09) -> list[tuple[float, float]] | None:
    """Convert face samples into a steady camera: hold position, and only move
    when the face has clearly left the current framing. Returns step keyframes
    (time, centre_x), or None when faces are too rare to trust."""
    seen = [x for _, x in samples if x is not None]
    if len(seen) < max(3, 0.5 * len(samples)):  # mostly wide shots: use the blurred "fit" layout instead
        return None

    cam = statistics.median(seen[: max(3, len(seen) // 10)])
    keys = [(0.0, cam)]
    pending: list[float] = []
    for t, x in samples:
        if x is None:
            continue
        if abs(x - cam) > deadzone:
            pending.append(x)
            if len(pending) >= 3:  # a full second off-centre: a real move, not a flicker
                cam = statistics.median(pending)
                keys.append((max(0.0, t - 0.6), float(cam)))
                pending = []
        else:
            pending = []
    return keys[:60]


def _crop_x_expr(keys: list[tuple[float, float]], src_w: int, crop_w: int) -> str:
    def px(cx: float) -> int:
        return int(max(0, min(src_w - crop_w, cx * src_w - crop_w / 2)))

    expr = str(px(keys[-1][1]))
    for i in range(len(keys) - 2, -1, -1):
        expr = f"if(lt(t,{keys[i + 1][0]:.2f}),{px(keys[i][1])},{expr})"
    return expr


# ---------- captions ----------

def _ass_time(t: float) -> str:
    t = max(t, 0)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _groups(words: list[Word], max_words: int = 3, max_chars: int = 18) -> list[list[Word]]:
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        chars = sum(len(x.text) for x in cur) + len(cur)
        gap = (w.start - cur[-1].end) if cur else 0
        if cur and (len(cur) >= max_words or chars + len(w.text) > max_chars or gap > 0.6):
            groups.append(cur)
            cur = []
        cur.append(w)
        if w.text[-1:] in ".?!,":
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[Word], clip_start: float, clip_len: float, style_key: str, hook: str | None) -> str:
    st = STYLES.get(style_key, STYLES["yellow"])
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{st['size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,470,1
Style: Hook,Arial Black,64,&H00101010,&H00101010,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = []
    if hook:
        text = _esc(hook.upper())
        lines.append(
            f"Dialogue: 1,{_ass_time(0)},{_ass_time(min(3.5, clip_len))},Hook,,0,0,0,,"
            f"{{\\fad(120,250)}}{text}"
        )

    for group in _groups(words):
        for i, w in enumerate(group):
            s = w.start - clip_start
            e = (group[i + 1].start if i + 1 < len(group) else w.end) - clip_start
            e = min(e, clip_len)
            if e <= 0 or s >= clip_len or e - s < 0.02:
                continue
            parts = []
            for j, x in enumerate(group):
                tok = _esc(x.text.upper() if st["upper"] else x.text)
                if j == i:
                    parts.append(f"{{\\c{st['active']}\\fscx108\\fscy108}}{tok}{{\\c&HFFFFFF&\\fscx100\\fscy100}}")
                else:
                    parts.append(tok)
            pop = "{\\fscx86\\fscy86\\t(0,90,\\fscx100\\fscy100)}" if i == 0 else ""
            lines.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    return head + "\n".join(lines) + "\n"


# ---------- encode ----------

def _probe_size(video: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def render_clip(
    video: Path,
    words: list[Word],
    start: float,
    end: float,
    out_dir: Path,
    name: str,
    style: str = "yellow",
    layout: str = "auto",
    hook: str | None = None,
) -> dict:
    """Writes <name>.mp4 and <name>.jpg into out_dir. Returns what layout was used."""
    clip_len = end - start
    clip_words = [w for w in words if w.end > start and w.start < end]
    ass_name = f"{name}.ass"
    (out_dir / ass_name).write_text(build_ass(clip_words, start, clip_len, style, hook), encoding="utf-8")

    src_w, src_h = _probe_size(video)
    vertical_already = src_w / src_h <= 0.6
    used = layout
    keys = None
    if layout in ("auto", "fill") and not vertical_already:
        keys = camera_path(track_faces(video, start, end))
        if layout == "auto":
            used = "fill" if keys else "fit"
        elif keys is None:
            keys = [(0.0, 0.5)]  # forced fill with no face: centre crop

    if vertical_already:
        used = "source"
        graph = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},ass={ass_name}[v]"
    elif used == "fill":
        crop_w = int(src_h * 9 / 16) // 2 * 2
        x = _crop_x_expr(keys, src_w, crop_w)
        graph = f"[0:v]crop={crop_w}:{src_h}:x='{x}':y=0,scale={W}:{H}:flags=lanczos,ass={ass_name}[v]"
    else:  # fit: whole frame over a blurred copy of itself
        graph = (
            f"[0:v]split[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:4,eq=brightness=-0.12[bg];"
            f"[b]scale={W}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,ass={ass_name}[v]"
        )

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-t", f"{clip_len:.3f}", "-i", str(video),
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
        "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", f"{name}.mp4",
    ]
    # cwd=out_dir so the ass filter gets a bare filename: Windows paths with
    # colons and apostrophes can't be escaped reliably inside a filter graph.
    proc = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-600:]}")

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{min(1.0, clip_len / 2):.2f}", "-i", f"{name}.mp4",
         "-frames:v", "1", "-vf", "scale=360:-2", f"{name}.jpg"],
        cwd=out_dir, capture_output=True,
    )
    (out_dir / ass_name).unlink(missing_ok=True)
    return {"layout": used}
