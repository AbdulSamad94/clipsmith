"""Upload a YouTube cookies.txt from the page, so users never edit .env."""
import io

import pytest
from fastapi.testclient import TestClient

from app import config, main, source

GOOD = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tabc\n"
    ".google.com\tTRUE\t/\tTRUE\t1999999999\tHSID\tdef\n"
)


@pytest.fixture
def cookie_path(monkeypatch, tmp_path):
    p = tmp_path / "youtube_cookies.txt"
    monkeypatch.setattr(config, "COOKIES_FILE", p)
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)
    return p


@pytest.fixture
def client(monkeypatch, cookie_path):
    monkeypatch.setattr(main._pool, "submit", lambda fn, *a: None)
    monkeypatch.setattr(main, "_jobs", {})
    return TestClient(main.app)


def _up(client, data: bytes, name="youtube.com_cookies.txt"):
    return client.post("/api/cookies", files={"file": (name, io.BytesIO(data), "text/plain")})


# --- validation (pure) ---

def test_valid_netscape_file_is_accepted():
    assert source.check_cookies(GOOD) == 2


def test_bom_and_httponly_prefix_are_fine():
    text = "﻿# Netscape HTTP Cookie File\n#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tx\n"
    assert source.check_cookies(text) == 1


@pytest.mark.parametrize("text", [
    "",
    "not a cookies file at all",
    '[{"domain": ".youtube.com", "name": "SID"}]',  # JSON export, wrong format
    "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tSID\tx\n",  # no YouTube cookies
])
def test_bad_files_are_rejected(text):
    with pytest.raises(ValueError):
        source.check_cookies(text)


# --- yt-dlp picks up the uploaded file ---

def test_uploaded_file_is_used_by_yt_dlp(cookie_path):
    cookie_path.write_text(GOOD)
    assert source._ydl_base()["cookiefile"] == str(cookie_path)


def test_env_cookie_file_wins_over_uploaded(cookie_path, monkeypatch, tmp_path):
    cookie_path.write_text(GOOD)
    env = tmp_path / "env.txt"
    env.write_text(GOOD)
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(env))
    assert source._ydl_base()["cookiefile"] == str(env)


def test_uploaded_file_wins_over_browser(cookie_path, monkeypatch):
    cookie_path.write_text(GOOD)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    opts = source._ydl_base()
    assert opts["cookiefile"] == str(cookie_path) and "cookiesfrombrowser" not in opts


# --- API ---

def test_status_when_nothing_set(client):
    assert client.get("/api/cookies").json() == {"set": False, "source": None, "added": None}


def test_upload_saves_and_reports(client, cookie_path):
    res = _up(client, GOOD.encode())
    assert res.status_code == 200
    body = res.json()
    assert body["set"] is True and body["source"] == "upload" and body["added"]
    assert cookie_path.read_text() == GOOD
    assert client.get("/api/cookies").json()["set"] is True


def test_upload_rejects_bad_file_and_keeps_old(client, cookie_path):
    cookie_path.write_text(GOOD)
    res = _up(client, b"hello")
    assert res.status_code == 400
    assert "cookies.txt" in res.json()["detail"]
    assert cookie_path.read_text() == GOOD


def test_upload_rejects_huge_file(client, cookie_path):
    res = _up(client, b"#" * (2 * 1024 * 1024))
    assert res.status_code == 413
    assert not cookie_path.exists()


def test_delete_removes_file(client, cookie_path):
    cookie_path.write_text(GOOD)
    assert client.delete("/api/cookies").json()["set"] is False
    assert not cookie_path.exists()


def test_status_reports_env_settings(client, monkeypatch):
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    assert client.get("/api/cookies").json()["source"] == "browser"


def test_cross_origin_upload_is_refused(client):
    res = client.post("/api/cookies", files={"file": ("c.txt", io.BytesIO(GOOD.encode()), "text/plain")},
                      headers={"Origin": "https://evil.example"})
    assert res.status_code == 403


# --- failed jobs say why, so the page can offer the fix ---

def test_bot_check_gets_an_error_code():
    exc = Exception("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies")
    assert main.error_code(exc) == "bot_check"
    assert main.error_code(Exception("something else")) is None


def test_bot_check_message_points_to_the_page():
    msg = main.friendly_error(Exception("Sign in to confirm you're not a bot"))
    assert "cookies" in msg.lower() and "--cookies" not in msg
