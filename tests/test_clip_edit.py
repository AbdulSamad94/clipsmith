"""Clip editor: change a finished clip's start/end, caption text or title and
re-render just that clip. Rendering and trimming are patched out."""
import json

import pytest
from fastapi.testclient import TestClient

from app import main, render, source, trim
from app.source import Word

YT = "https://www.youtube.com/watch?v=abc123"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main._pool, "submit", lambda fn, *a: None)
    monkeypatch.setattr(main, "_jobs", {})
    return TestClient(main.app)


@pytest.fixture
def renders(monkeypatch):
    calls = []

    def fake_render(video, words, start, end, out_dir, name, **k):
        calls.append({"video": video, "words": words, "start": start, "end": end, "name": name, **k})
        (out_dir / f"{name}.mp4").write_bytes(b"v")
        (out_dir / f"{name}.jpg").write_bytes(b"j")
        return {"layout": "fit", "length": end - start}

    monkeypatch.setattr(render, "render_clip", fake_render)
    monkeypatch.setattr(trim, "plan", lambda *a, **k: [(0.0, 1.0)])
    return calls


def _job(client, words=None, keep_source=True, status="done", **opts):
    job = client.post("/api/jobs", json={"url": YT, **opts}).json()
    jid = job["id"]
    d = main._job_dir(jid)
    d.mkdir(parents=True, exist_ok=True)
    words = words or [Word(f"w{i}", i * 1.0, i * 1.0 + 0.5) for i in range(60)]
    if keep_source:
        (d / "source.mp4").write_bytes(b"src")
        main._save_transcript(jid, words)
    for n in ("clip_01", "clip_02"):
        (d / f"{n}.mp4").write_bytes(b"v")
        (d / f"{n}.jpg").write_bytes(b"j")
    main._jobs[jid].update(status=status, duration=60.0, clips=[
        {"title": "One", "hook": "Look", "start": 10.0, "end": 20.0, "length": 10.0,
         "video": f"/media/{jid}/clip_01.mp4", "thumb": f"/media/{jid}/clip_01.jpg", "layout": "fit"},
        {"title": "Two", "hook": "", "start": 30.0, "end": 40.0, "length": 10.0,
         "video": f"/media/{jid}/clip_02.mp4", "thumb": f"/media/{jid}/clip_02.jpg", "layout": "fit"},
    ])
    return jid


def _edit(client, jid, index=0, **body):
    return client.post(f"/api/jobs/{jid}/clips/{index}/edit", json=body)


# ---------- pure caption retiming ----------

def test_same_word_count_keeps_each_words_timing():
    words = [Word("hello", 1.0, 1.4), Word("wrold", 1.5, 2.0)]
    out = main._retime_words(words, 0.0, 5.0, "Hello world")
    assert [(w.text, w.start, w.end) for w in out] == [("Hello", 1.0, 1.4), ("world", 1.5, 2.0)]


def test_different_word_count_spreads_over_the_spoken_span():
    words = [Word("a", 2.0, 2.5), Word("b", 3.0, 4.0)]
    out = main._retime_words(words, 0.0, 10.0, "one two three four")
    assert [w.text for w in out] == ["one", "two", "three", "four"]
    assert out[0].start == pytest.approx(2.0) and out[-1].end == pytest.approx(4.0)
    assert all(a.end <= b.start + 1e-9 for a, b in zip(out, out[1:]))


def test_text_with_no_speech_in_range_spreads_over_the_clip():
    out = main._retime_words([], 5.0, 9.0, "added caption")
    assert out[0].start == pytest.approx(5.0) and out[-1].end == pytest.approx(9.0)


def test_empty_text_means_no_captions():
    assert main._retime_words([Word("a", 1, 2)], 0, 3, "   ") == []


# ---------- transcript endpoint ----------

def test_transcript_for_a_range(client):
    jid = _job(client)
    res = client.get(f"/api/jobs/{jid}/transcript", params={"start": 10, "end": 13})
    assert res.status_code == 200
    assert res.json()["text"] == "w10 w11 w12"


# ---------- edit endpoint ----------

def test_edit_rerenders_with_new_bounds(client, renders):
    jid = _job(client)
    res = _edit(client, jid, start=12.0, end=25.0)
    assert res.status_code == 200, res.text
    clip = res.json()["clips"][0]
    assert (clip["start"], clip["end"]) == (12.0, 25.0)
    assert len(renders) == 1
    call = renders[0]
    assert (call["start"], call["end"]) == (12.0, 25.0)
    assert call["video"].name == "source.mp4"
    assert call["hook"] == "Look" and call["style"] == "yellow" and call["aspect"] == "9:16"
    assert [w.text for w in call["words"] if w.end > 12.0][:2] == ["w12", "w13"]
    # new file name so the browser doesn't show a cached old version; old files removed
    assert clip["video"] != f"/media/{jid}/clip_01.mp4"
    d = main._job_dir(jid)
    assert not (d / "clip_01.mp4").exists()
    assert (d / main.Path(clip["video"]).name).exists()
    # persisted, and the other clip untouched
    saved = json.loads((d / "job.json").read_text(encoding="utf-8"))
    assert saved["clips"][0]["start"] == 12.0 and saved["clips"][1]["title"] == "Two"


def test_edit_text_replaces_captions(client, renders):
    jid = _job(client)
    res = _edit(client, jid, start=10.0, end=13.0, text="ten eleven twelve")
    assert res.status_code == 200, res.text
    assert [w.text for w in renders[0]["words"]] == ["ten", "eleven", "twelve"]
    assert res.json()["clips"][0]["text"] == "ten eleven twelve"


def test_title_only_edit_skips_rendering(client, renders):
    jid = _job(client)
    res = _edit(client, jid, start=10.0, end=20.0, title="Better title")
    assert res.status_code == 200
    assert res.json()["clips"][0]["title"] == "Better title"
    assert renders == []


def test_trim_setting_is_honoured(client, renders):
    jid = _job(client, trim_pauses=True)
    _edit(client, jid, start=11.0, end=20.0)
    assert renders[0]["keep"] == [(0.0, 1.0)]


@pytest.mark.parametrize("body, code", [
    ({"start": 20.0, "end": 10.0}, 400),
    ({"start": -1.0, "end": 10.0}, 400),
    ({"start": 50.0, "end": 61.0}, 400),
    ({"start": 10.0, "end": 10.5}, 400),
])
def test_bad_bounds_are_refused(client, renders, body, code):
    jid = _job(client)
    assert _edit(client, jid, **body).status_code == code
    assert renders == []


def test_missing_clip_is_404(client, renders):
    jid = _job(client)
    assert _edit(client, jid, index=5, start=1.0, end=5.0).status_code == 404
    assert client.post("/api/jobs/0000000000/clips/0/edit", json={"start": 1, "end": 5}).status_code == 404


def test_unfinished_job_is_409(client, renders):
    jid = _job(client, status="running")
    assert _edit(client, jid, start=11.0, end=20.0).status_code == 409


def test_without_source_rerender_is_409_but_title_still_editable(client, renders):
    jid = _job(client, keep_source=False)
    res = _edit(client, jid, start=11.0, end=20.0)
    assert res.status_code == 409 and "source" in res.json()["detail"].lower()
    assert _edit(client, jid, start=10.0, end=20.0, title="T").status_code == 200


def test_clip_being_uploaded_is_409(client, renders):
    jid = _job(client)
    main._jobs[jid]["clips"][0]["youtube"] = {"status": "uploading"}
    assert _edit(client, jid, start=11.0, end=20.0).status_code == 409


def test_caption_fx_options_are_forwarded_when_saved(client, renders):
    jid = _job(client)
    main._jobs[jid]["options"].update(highlight_keywords=True, emoji=True)
    assert _edit(client, jid, start=11.0, end=20.0).status_code == 200
    assert renders[0]["highlight"] is True and renders[0]["emoji"] is True


def test_caption_fx_options_not_passed_when_absent(client, renders):
    jid = _job(client)
    for k in ("highlight_keywords", "emoji"):
        main._jobs[jid]["options"].pop(k, None)
    assert _edit(client, jid, start=11.0, end=20.0).status_code == 200
    assert "highlight" not in renders[0] and "emoji" not in renders[0]


def test_cross_origin_edit_is_refused(client, renders):
    jid = _job(client)
    res = client.post(f"/api/jobs/{jid}/clips/0/edit", json={"start": 11.0, "end": 20.0},
                      headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert renders == []


# ---------- pipeline keeps what re-rendering needs ----------

def test_pipeline_keeps_source_and_transcript(monkeypatch, client, renders):
    words = [Word(f"w{i}.", i * 1.0, i * 1.0 + 0.5) for i in range(120)]
    from app import selector

    def fake_download(url, workdir, progress):
        video = workdir / "source.mp4"
        video.write_bytes(b"x")
        return source.Source(video, "T", 120.0, "en", words, "youtube-captions")

    monkeypatch.setattr(source, "download", fake_download)
    clip = selector.Clip(10.0, 50.0, "t", "", 80, "r", "d", [])
    monkeypatch.setattr(selector, "select", lambda *a, **k: ([clip], "basic", None))
    req = main.JobRequest(url="https://youtu.be/x")
    job = main._new_job(req, "00000000bb")
    main._run(job["id"], req)
    assert main._jobs["00000000bb"]["status"] == "done", main._jobs["00000000bb"].get("error")
    d = main._job_dir("00000000bb")
    assert (d / "source.mp4").exists()
    assert [w.text for w in main._load_transcript("00000000bb")][:2] == ["w0.", "w1."]
