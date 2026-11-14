import pytest
from fastapi.testclient import TestClient

from app import main

YT = "https://www.youtube.com/watch?v=abc123"


@pytest.fixture
def client(monkeypatch):
    submitted = []
    monkeypatch.setattr(main._pool, "submit", lambda fn, *a: submitted.append(a))  # never run the pipeline
    monkeypatch.setattr(main, "_jobs", {})
    c = TestClient(main.app)
    c.submitted = submitted
    return c


def test_status_reports_styles(client):
    data = client.get("/api/status").json()
    assert set(data["styles"]) == {"yellow", "green", "clean"}
    assert "missing" in data


def test_create_job_queues_it(client):
    res = client.post("/api/jobs", json={"url": YT, "clip_count": 3})
    assert res.status_code == 200
    job = res.json()
    assert job["status"] == "queued" and job["options"]["clip_count"] == 3
    assert len(client.submitted) == 1
    assert client.get(f"/api/jobs/{job['id']}").json()["id"] == job["id"]


@pytest.mark.parametrize("body, message", [
    ({"url": "https://example.com/video"}, "YouTube"),
    ({"url": YT, "min_len": 60, "max_len": 30}, "shorter"),
    ({"url": YT, "style": "rainbow"}, "caption style"),
    ({"url": YT, "layout": "zoom"}, "layout"),
])
def test_create_job_rejects_bad_input(client, body, message):
    res = client.post("/api/jobs", json=body)
    assert res.status_code == 400
    assert message in res.json()["detail"]
    assert client.submitted == []


def test_clip_count_is_bounded(client):
    assert client.post("/api/jobs", json={"url": YT, "clip_count": 99}).status_code == 422


def test_short_links_are_accepted(client):
    assert client.post("/api/jobs", json={"url": "https://youtu.be/abc123"}).status_code == 200


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_cannot_delete_running_job(client):
    job = client.post("/api/jobs", json={"url": YT}).json()
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 409


def test_delete_finished_job(client):
    job = client.post("/api/jobs", json={"url": YT}).json()
    main._jobs[job["id"]]["status"] = "done"
    assert client.delete(f"/api/jobs/{job['id']}").json() == {"ok": True}
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
