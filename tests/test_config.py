import pytest

from app import config

KEYS = (
    "AI_PROVIDER",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OLLAMA_URL",
    "OLLAMA_HOST",
)


@pytest.fixture
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(config, "OLLAMA_EXE", "")
    return monkeypatch


def test_no_configuration_means_basic(clean_env):
    assert config.ai_provider() is None


def test_forced_provider_wins(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "x")
    clean_env.setenv("AI_PROVIDER", "ollama")
    assert config.ai_provider() == "ollama"


def test_forced_none(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "x")
    clean_env.setenv("AI_PROVIDER", "none")
    assert config.ai_provider() is None


def test_gemini_preferred_over_claude(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "x")
    clean_env.setenv("ANTHROPIC_API_KEY", "y")
    assert config.ai_provider() == "gemini"


def test_ollama_detected_from_executable(clean_env, tmp_path):
    exe = tmp_path / "ollama.exe"
    exe.write_text("")
    clean_env.setattr(config, "OLLAMA_EXE", str(exe))
    assert config.ai_provider() == "ollama"


def test_ollama_detected_from_url(clean_env):
    clean_env.setenv("OLLAMA_URL", "http://ollama:11434")
    assert config.ai_provider() == "ollama"


def test_ollama_detected_from_host(clean_env):
    clean_env.setenv("OLLAMA_HOST", "ollama:11434")
    assert config.ai_provider() == "ollama"


def test_forced_none_beats_ollama_url(clean_env):
    clean_env.setenv("OLLAMA_URL", "http://ollama:11434")
    clean_env.setenv("AI_PROVIDER", "none")
    assert config.ai_provider() is None


def test_gemini_preferred_over_ollama_url(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "x")
    clean_env.setenv("OLLAMA_URL", "http://ollama:11434")
    assert config.ai_provider() == "gemini"


@pytest.mark.parametrize("url, host, expected", [
    (None, None, "http://127.0.0.1:11434"),
    ("http://ollama:11434/", None, "http://ollama:11434"),
    ("ollama:11434/", None, "http://ollama:11434"),
    (None, "ollama:11434", "http://ollama:11434"),
    (None, "https://ollama.example.com/", "https://ollama.example.com"),
    ("http://primary:11434/", "fallback:11434", "http://primary:11434"),
    (None, ":11434", "http://127.0.0.1:11434"),
])
def test_resolve_ollama_url(clean_env, url, host, expected):
    if url is not None:
        clean_env.setenv("OLLAMA_URL", url)
    if host is not None:
        clean_env.setenv("OLLAMA_HOST", host)
    assert config.resolve_ollama_url() == expected

