"""Podcast layout: two speakers stacked top/bottom, and steadier single-face framing."""
import random
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import main, render

LEFT = (0.28, 0.42, 0.14, 0.25)   # two-shot interview, 1920x1080
RIGHT = (0.72, 0.40, 0.13, 0.24)


def _two_shot(n=60, both_rate=0.8, seed=3, jitter=0.015):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        faces = []
        for box in (LEFT, RIGHT):
            if rnd.random() < both_rate:
                cx, cy, w, h = box
                faces.append((cx + rnd.uniform(-jitter, jitter), cy + rnd.uniform(-jitter, jitter), w, h))
        out.append((i / 3, faces))
    return out


# ---------- finding the pair ----------

def test_two_steady_faces_are_a_podcast_pair():
    pair = render.podcast_pair(_two_shot())
    assert pair is not None
    left, right = pair
    assert abs(left[0] - LEFT[0]) < 0.03 and abs(right[0] - RIGHT[0]) < 0.03


def test_single_talking_head_is_not_a_pair():
    frames = [(i / 3, [(0.5, 0.4, 0.2, 0.35)]) for i in range(60)]
    assert render.podcast_pair(frames) is None


def test_second_face_seen_rarely_is_not_a_pair():
    frames = _two_shot()
    frames = [(t, f if i % 6 == 0 else f[:1]) for i, (t, f) in enumerate(frames)]
    assert render.podcast_pair(frames) is None


def test_faces_too_close_together_are_not_a_pair():
    frames = [(i / 3, [(0.45, 0.4, 0.12, 0.2), (0.55, 0.4, 0.12, 0.2)]) for i in range(60)]
    assert render.podcast_pair(frames) is None


def test_tiny_wide_shot_faces_are_not_a_pair():
    frames = [(i / 3, [(0.3, 0.5, 0.04, 0.07), (0.7, 0.5, 0.04, 0.07)]) for i in range(60)]
    assert render.podcast_pair(frames) is None


def test_no_faces_is_not_a_pair():
    assert render.podcast_pair([(i / 3, []) for i in range(30)]) is None
    assert render.podcast_pair([]) is None


# ---------- geometry ----------

def _check_rect(rect, src_w, src_h):
    x, y, w, h = rect
    assert all(v % 2 == 0 for v in rect), rect
    assert x >= 0 and y >= 0 and w > 0 and h > 0
    assert x + w <= src_w and y + h <= src_h


@pytest.mark.parametrize("src", [(1920, 1080), (1280, 720), (854, 480), (1440, 1080)])
def test_podcast_geometry_crops_each_face_in_panel_shape(src):
    sw, sh = src
    g = render.podcast_layout(sw, sh, LEFT, RIGHT, 1080, 1920)
    assert g is not None
    assert g["top_h"] + g["bottom_h"] == 1920 and g["top_h"] % 2 == 0
    for key, face, panel_h in (("top", LEFT, g["top_h"]), ("bottom", RIGHT, g["bottom_h"])):
        _check_rect(g[key], sw, sh)
        x, y, w, h = g[key]
        assert abs(w / h - 1080 / panel_h) < 0.02  # nothing is stretched
        fx, fy = face[0] * sw, face[1] * sh
        assert x <= fx <= x + w and y <= fy <= y + h  # the face is in its own panel


def test_podcast_geometry_puts_left_speaker_on_top():
    g = render.podcast_layout(1920, 1080, RIGHT, LEFT, 1080, 1920)  # order given doesn't matter
    assert g["top"][0] < g["bottom"][0]


def test_podcast_geometry_needs_a_tall_frame():
    assert render.podcast_layout(1920, 1080, LEFT, RIGHT, 1920, 1080) is None


# ---------- steadier single-face framing ----------

def test_tracking_sticks_with_the_same_face_when_sizes_are_close():
    """Two similar faces: the largest flips every frame from detector noise.
    The crop should stay on one person instead of jittering between them."""
    frames = []
    for i in range(30):
        a, b = (0.20, 0.21) if i % 2 else (0.21, 0.20)
        frames.append((i / 3, [(0.3, 0.4, a, a), (0.7, 0.4, b, b)]))
    xs = {x for _, x in render.track_samples(frames)}
    assert len(xs) == 1


def test_tracking_switches_to_a_clearly_bigger_face():
    frames = [(i / 3, [(0.3, 0.4, 0.15, 0.2)]) for i in range(5)]
    frames += [(5 + i / 3, [(0.3, 0.4, 0.10, 0.15), (0.7, 0.4, 0.3, 0.4)]) for i in range(5)]
    xs = [x for _, x in render.track_samples(frames)]
    assert xs[0] == 0.3 and xs[-1] == 0.7


# ---------- API ----------

def test_api_accepts_podcast_layout(monkeypatch):
    monkeypatch.setattr(main._pool, "submit", lambda *a: None)
    monkeypatch.setattr(main, "_jobs", {})
    res = TestClient(main.app).post("/api/jobs", json={"url": "https://youtu.be/x", "layout": "podcast"})
    assert res.status_code == 200 and res.json()["options"]["layout"] == "podcast"


def test_ui_offers_podcast_layout():
    html = (render.config.ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert '<option value="podcast">' in html


# ---------- render branch (ffmpeg mocked away) ----------

def _fake_render(monkeypatch, frames, size=(1920, 1080)):
    calls = []
    monkeypatch.setattr(render, "_probe_size", lambda v: size)
    monkeypatch.setattr(render, "detect_faces", lambda *a, **k: frames)

    class P:
        returncode, stderr = 0, ""

    monkeypatch.setattr(render.subprocess, "run", lambda cmd, **k: calls.append(cmd) or P())
    return calls


def test_render_uses_podcast_stack_when_two_faces(monkeypatch, tmp_path):
    calls = _fake_render(monkeypatch, _two_shot())
    info = render.render_clip(tmp_path / "v.mp4", [], 0, 20, tmp_path, "c", layout="podcast")
    assert info["layout"] == "podcast"
    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "vstack" in graph and graph.count("crop=") == 2


def test_render_podcast_falls_back_to_tracking_with_one_face(monkeypatch, tmp_path):
    frames = [(i / 3, [(0.4, 0.4, 0.2, 0.3)]) for i in range(30)]
    calls = _fake_render(monkeypatch, frames)
    info = render.render_clip(tmp_path / "v.mp4", [], 0, 10, tmp_path, "c", layout="podcast")
    assert info["layout"] == "fill"
    assert "vstack" not in calls[0][calls[0].index("-filter_complex") + 1]


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
def test_real_podcast_render_is_vertical(tmp_path, monkeypatch):
    src = tmp_path / "pod.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=30",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    monkeypatch.setattr(render, "detect_faces", lambda *a, **k: _two_shot())
    info = render.render_clip(src, [], 0, 2, tmp_path, "clip", layout="podcast")
    assert info["layout"] == "podcast"
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(tmp_path / "clip.mp4")], capture_output=True, text=True).stdout.strip()
    assert out == "1080,1920"
