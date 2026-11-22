"""YouTube "Sign in to confirm you're not a bot": let yt-dlp use the user's cookies."""
from app import source
from app.main import friendly_error


def _clear(monkeypatch):
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)


def test_no_cookie_options_by_default(monkeypatch):
    _clear(monkeypatch)
    opts = source._ydl_base()
    assert "cookiefile" not in opts
    assert "cookiesfrombrowser" not in opts


def test_cookies_file_is_passed_when_it_exists(monkeypatch, tmp_path):
    _clear(monkeypatch)
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(f))
    assert source._ydl_base()["cookiefile"] == str(f)


def test_missing_cookies_file_raises_a_clear_error(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(tmp_path / "nope.txt"))
    try:
        source._ydl_base()
    except RuntimeError as e:
        assert "YTDLP_COOKIES_FILE" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_browser_name_becomes_a_yt_dlp_tuple(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "Firefox")
    assert source._ydl_base()["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_browser_with_profile(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox:work")
    assert source._ydl_base()["cookiesfrombrowser"] == ("firefox", "work", None, None)


def test_cookies_file_wins_over_browser(monkeypatch, tmp_path):
    _clear(monkeypatch)
    f = tmp_path / "cookies.txt"
    f.write_text("")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(f))
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    opts = source._ydl_base()
    assert opts["cookiefile"] == str(f)
    assert "cookiesfrombrowser" not in opts


def test_bot_check_error_explains_the_cookie_fix():
    raw = ("ERROR: [youtube] Ra6sNe8s2Hc: Sign in to confirm you’re not a bot. "
           "Use --cookies-from-browser or --cookies for the authentication.")
    msg = friendly_error(Exception(raw))
    assert "YTDLP_COOKIES_FROM_BROWSER" in msg
    assert "--cookies" not in msg
