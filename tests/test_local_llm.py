import types

import pytest
import requests

from app import config, local_llm


def test_ensure_running_skips_popen_when_already_reachable(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama:11434")
    monkeypatch.setattr(local_llm.requests, "get", lambda url, timeout=3: types.SimpleNamespace(status_code=200))
    called = []
    monkeypatch.setattr(local_llm.subprocess, "Popen", lambda *a, **kw: called.append(a))

    local_llm.ensure_running()
    assert called == []


def test_ensure_running_non_loopback_unreachable_does_not_spawn_and_raises(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama:11434")
    monkeypatch.setattr(config, "OLLAMA_EXE", "/usr/bin/ollama")
    monkeypatch.setattr(local_llm.os.path, "exists", lambda p: True)

    def fail_get(*a, **kw):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(local_llm.requests, "get", fail_get)
    called = []
    monkeypatch.setattr(local_llm.subprocess, "Popen", lambda *a, **kw: called.append(a))

    with pytest.raises(RuntimeError) as exc:
        local_llm.ensure_running()

    assert called == []
    msg = str(exc.value)
    assert "http://ollama:11434" in msg
    assert "ollama.exe" not in msg


def test_ensure_running_loopback_starts_local_server(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(config, "OLLAMA_EXE", "/fake/ollama")
    monkeypatch.setattr(config, "OLLAMA_MODELS_DIR", "/custom/models")
    monkeypatch.setattr(local_llm.os.path, "exists", lambda p: p == "/fake/ollama")
    monkeypatch.setattr(local_llm.time, "sleep", lambda _: None)

    attempts = {"n": 0}

    def fake_get(*a, **kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise requests.ConnectionError("not running yet")
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr(local_llm.requests, "get", fake_get)
    spawned = []
    monkeypatch.setattr(local_llm.subprocess, "Popen", lambda cmd, **kw: spawned.append((cmd, kw)))

    local_llm.ensure_running()

    assert len(spawned) == 1
    cmd, kw = spawned[0]
    assert cmd == ["/fake/ollama", "serve"]
    assert kw["env"]["OLLAMA_MODELS"] == "/custom/models"


def test_ensure_running_loopback_missing_exe_raises(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(config, "OLLAMA_EXE", "")
    monkeypatch.setattr(local_llm.requests, "get", lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError()))

    with pytest.raises(RuntimeError, match="OLLAMA_EXE"):
        local_llm.ensure_running()


def test_chat_json_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama:11434")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen3.5:4b")
    monkeypatch.setattr(config, "OLLAMA_CTX", 8192)
    monkeypatch.setattr(local_llm, "ensure_running", lambda: None)

    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        return types.SimpleNamespace(
            status_code=200,
            json=lambda: {"message": {"content": '{"clips": []}'}},
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(local_llm.requests, "post", fake_post)

    out = local_llm.chat_json("sys", "usr", {"type": "object"})
    assert out == '{"clips": []}'
    assert seen["url"] == "http://ollama:11434/api/chat"
    assert seen["json"]["model"] == "qwen3.5:4b"
    assert seen["json"]["stream"] is False
    assert seen["json"]["think"] is False
    assert seen["json"]["options"]["num_ctx"] == 8192


def test_chat_json_404_mentions_ollama_pull(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama:11434")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen3.5:4b")
    monkeypatch.setattr(local_llm, "ensure_running", lambda: None)
    monkeypatch.setattr(
        local_llm.requests,
        "post",
        lambda *a, **kw: types.SimpleNamespace(status_code=404),
    )

    with pytest.raises(RuntimeError) as exc:
        local_llm.chat_json("sys", "usr", {})

    msg = str(exc.value)
    assert "qwen3.5:4b" in msg
    assert "ollama pull qwen3.5:4b" in msg
    assert "Stop-Process" not in msg


def test_unload_ignores_request_errors(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama:11434")

    def fail_post(*a, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(local_llm.requests, "post", fail_post)
    local_llm.unload()
