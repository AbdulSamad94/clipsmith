# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Clipsmith: a local, offline FastAPI app that turns a long YouTube video (or uploaded file) into ranked, captioned vertical Shorts. Python 3.10+, needs ffmpeg on PATH; AI moment-picking uses Ollama by default.

## Commands

```
setup.bat / ./setup.sh                 # create .venv and install requirements
run.bat / ./run.sh                     # uvicorn app.main:app on http://127.0.0.1:8765
pip install -r requirements-dev.txt
python -m pytest                       # full suite (pytest.ini: testpaths=tests, -q)
python -m pytest tests/test_trim.py::test_name   # single test
```

CI (`.github/workflows/tests.yml`) runs pytest on Ubuntu + Windows, Python 3.10 and 3.12. There is no linter configured.

## Architecture

Pipeline, driven by `_run()` in `app/main.py` on a background thread per job:

1. `app/source.py` — downloads via yt-dlp (or takes an upload saved as `source.*`) and produces a word-level transcript (`Word(text, start, end)`), from YouTube captions or Whisper fallback.
2. `app/selector.py` — `to_sentences` → `within(start_time, end_time)` → `select(...)` returns scored clips (title, hook, caption, hashtags). Uses the provider from `config.ai_provider()` (`ollama` via `app/local_llm.py`, `gemini`, `claude`, or `none` = rule-based) and returns the method used plus a warning when it falls back.
3. `app/trim.py` — optional pause/filler removal; `plan()` returns keep-ranges passed to render.
4. `app/render.py` — OpenCV face tracking, aspect crop (9:16/1:1/16:9) or blurred-background "split" layout, burned-in word captions, ffmpeg encode → `clip_NN.mp4` + `.jpg` thumb.
5. `app/youtube.py` — optional OAuth + upload/schedule of finished clips.

Job state is persisted as `data/jobs/<id>/job.json` (via `_save`/`_update`) and reloaded on startup by `_load_existing`; the in-memory `_jobs` dict is the live copy. Clips are appended to the job as each finishes so the UI shows them incrementally. Media is served at `/media/<job_id>/...`. The source video (`source.*`) and word timings (`transcript.json`) are kept in the job folder after rendering so a clip can be re-cut via the clip editor (`POST /api/jobs/{id}/clips/{index}/edit`, rendered on the same single-worker `_pool`); they are removed when the job is deleted. `CLIPSMITH_DATA_DIR` overrides the data folder.

`same_origin_only` middleware in `main.py` refuses any request whose Host isn't 127.0.0.1/localhost/::1 (DNS-rebinding) and cross-origin non-GET requests (CSRF). Extra hosts via `CLIPSMITH_ALLOWED_HOSTS` — tests set it to `testserver`.

The entire frontend is `static/index.html`: plain HTML/CSS/JS, no build step. UI changes must stay accessible (labels on every control, visible focus ring, ≥44px buttons, ≥4.5:1 contrast, no color-only info) and PRs need desktop + phone-width screenshots.

Configuration lives in `.env` (see `.env.example`); `app/config.py` loads it with `override=True`, so `.env` beats machine env vars.

## Testing rules

- Tests must not use the network, an AI model, ffmpeg, or a real video. Test pure functions directly and monkeypatch slow parts (see `tests/conftest.py`, `tests/test_api.py`).
- `conftest.py` sets `CLIPSMITH_DATA_DIR` to a temp dir before `app.config` is imported — keep that ordering. Use the `words_factory` fixture (a `|` token inserts a 1.5 s pause) and the `no_ai` fixture to force rule-based selection.
- Project practice is test-first.

## Constraints

- The app must keep working with no API key and no GPU (`AI_PROVIDER=none` / local Ollama on CPU).
- Never commit videos, clips, `data/`, or `.env`.
