import httpx
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.tools import HeaderChecker

TOKEN = "test-only-token-which-is-long-enough"
ORIGIN = "http://127.0.0.1:8001"


@pytest.fixture
def lab(tmp_path):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        headers = {"Set-Cookie": "private-secret", "Server": "private-server"}
        if request.url.path == "/hardened":
            headers.update({"Content-Security-Policy": "default-src 'none'", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "https://example.com", **headers})
        return httpx.Response(200, headers=headers, content="body-secret")

    settings = Settings(db_path=tmp_path / "lab.sqlite3", token=TOKEN)
    app = create_app(settings, HeaderChecker(transport=httpx.MockTransport(handle)))
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as client:
        yield client, app.state.store, calls, settings


def assessment(client, targets=None):
    response = client.post("/api/v1/assessments", json={"name": "Lab baseline", "targets": targets or [ORIGIN + "/vulnerable", ORIGIN + "/hardened", ORIGIN + "/redirect"], "authorization_confirmed": True})
    assert response.status_code == 201, response.text
    return response.json()


def proposal(client, assessment_id, target=ORIGIN + "/vulnerable"):
    response = client.post(f"/api/v1/assessments/{assessment_id}/actions", json={"tool": "http_headers", "target": target, "rationale": "Baseline check"})
    assert response.status_code == 201, response.text
    return response.json()


def completed(client, action):
    root = "/api/v1/actions/" + action["id"]
    assert client.post(root + "/approve", json={}).status_code == 200
    result = client.post(root + "/execute", json={})
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    return result.json()
