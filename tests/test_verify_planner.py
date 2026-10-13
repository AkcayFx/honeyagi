import asyncio
import getpass
import json
import httpx
import pytest
from fastapi.responses import JSONResponse
from app.config import Settings
from app.providers import OpenAICompatiblePlanner
from app import verify_planner as verifier
from conftest import TOKEN, ORIGIN


KEY = "test-only-verification-provider-key"
MODEL = "verification-test-model"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("PROVIDER", "MODEL", "BASE_URL", "API_KEY", "TIMEOUT", "MAX_TOKENS", "RESPONSE_FORMAT"):
        monkeypatch.delenv("SAP_PLANNER_" + name, raising=False)


def settings(tmp_path, **values):
    return Settings(**{"db_path": tmp_path / "operator.sqlite3", "token": TOKEN,
                       "planner_provider": "openai_compatible", "planner_model": MODEL,
                       "planner_base_url": "https://verification.example.invalid/v1",
                       "planner_api_key": KEY, **values})


def content(actions=None):
    return json.dumps({"summary": "UNTRUSTED MODEL WORDING MUST NOT ENTER VERIFICATION REPORT",
                       "actions": actions if actions is not None else [
        {"tool": "http_headers", "target": target, "rationale": "Observe headers"}
        for target in verifier.TARGETS]})


def provider(config, calls, *, raw=None, status=200):
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": content() if raw is None else raw}}]})
    return OpenAICompatiblePlanner(config, transport=httpx.MockTransport(handle))


def run(config, mock):
    return asyncio.run(verifier.verify(config, test_planner=mock))


def test_verification_preserves_operator_state_checks_approval_and_marks_simulation(tmp_path, capsys):
    config, calls = settings(tmp_path), []
    config.db_path.write_bytes(b"existing operator database must stay unchanged")
    result = run(config, provider(config, calls))
    assert result["status"] == "simulated" and result["workflow_passed"] is True
    assert result["live_verified"] is False and result["transport"] == "injected_test_provider"
    assert all(result["checks"].values())
    assert result["proposal_count"] == 2 and result["tool_calls"] == 0
    assert len(calls) == 1  # The UUID replay does not spend a second provider request.
    assert result["planning_http_status"] == 201
    assert result["elapsed_ms"] >= 0 and len(result["plan_sha256"]) == 64
    assert config.db_path.read_bytes() == b"existing operator database must stay unchanged"
    assert not list(tmp_path.glob("operator.sqlite3-*"))
    serialized = json.dumps(result)
    assert KEY not in serialized and TOKEN not in serialized
    assert "UNTRUSTED MODEL" not in serialized and "rationale" not in serialized
    assert "verification.example.invalid" not in serialized
    assert capsys.readouterr().out == ""  # The temporary dashboard token is never announced.


def test_unconfigured_mode_never_calls_provider_or_creates_database(tmp_path):
    config = Settings(token=TOKEN, db_path=tmp_path / "untouched.sqlite3")
    calls = []
    result = run(config, provider(settings(tmp_path), calls))
    assert result["status"] == "not_configured" and result["live_verified"] is False
    assert result["transport"] == "not_contacted" and calls == [] and not config.db_path.exists()


@pytest.mark.parametrize("status,raw,code", [
    (401, None, "provider_auth"), (429, None, "provider_rate_limited"),
    (500, None, "provider_failed"),
    (200, "not JSON", "schema_denied"),
    (200, content(actions=[{"tool": "http_headers", "target": "https://outside.example", "rationale": "Escape"}]), "scope_denied"),
    (200, content(actions=[]), "no_useful_proposals"),
])
def test_failure_records_remain_honest_and_do_not_run_tools(tmp_path, status, raw, code):
    config, calls = settings(tmp_path), []
    result = run(config, provider(config, calls, status=status, raw=raw))
    assert result["status"] == "failed" and result["failure_code"] == code
    assert result["live_verified"] is False and result["workflow_passed"] is False
    assert result["tool_calls"] == 0 and len(calls) == 1
    assert "UNTRUSTED MODEL" not in json.dumps(result) and KEY not in json.dumps(result)


def test_report_records_deadline_without_exception_contents(tmp_path):
    config = settings(tmp_path, planner_timeout=.01)
    async def handle(request):
        await asyncio.sleep(.1)
        raise RuntimeError(KEY)
    result = run(config, OpenAICompatiblePlanner(config, httpx.MockTransport(handle)))
    assert result["failure_code"] == "timeout" and result["planning_http_status"] == 504
    assert KEY not in json.dumps(result) and result["tool_calls"] == 0


@pytest.mark.parametrize("regression,expected", [
    ("approval", "unauthenticated_approval_allowed"), ("execution", "unexpected_tool_execution"),
])
def test_verifier_detects_execution_boundary_regressions(tmp_path, monkeypatch, regression, expected):
    config, calls = settings(tmp_path), []
    original = verifier.create_app
    def broken_app(*args, **kwargs):
        app = original(*args, **kwargs)
        @app.middleware("http")
        async def broken_boundary(request, call_next):
            if regression == "approval" and request.url.path.endswith("/approve"):
                return JSONResponse({"incorrectly_allowed": True})
            if regression == "execution" and request.url.path.endswith("/execute"):
                action_id = request.url.path.split("/")[-2]
                app.state.store.transition(action_id, "pending", "approved",
                                           "test_regression", {"test": True})
            return await call_next(request)
        return app
    monkeypatch.setattr(verifier, "create_app", broken_app)
    result = run(config, provider(config, calls))
    assert result["status"] == "failed" and result["live_verified"] is False
    assert result["failure_code"] == expected
    assert result["tool_calls"] == (1 if regression == "execution" else 0)


def test_report_creation_preserves_prior_runs_and_does_not_overwrite(tmp_path):
    first = verifier._new_result()
    second = verifier._new_result()
    first_path = verifier.save_result(first, tmp_path)
    second_path = verifier.save_result(second, tmp_path)
    assert first_path != second_path
    assert json.loads(first_path.read_text()) == first
    assert json.loads(second_path.read_text()) == second
    with pytest.raises(FileExistsError):
        verifier.save_result(first, tmp_path)
    assert json.loads(first_path.read_text()) == first


def test_saved_filename_must_be_a_uuid(tmp_path):
    with pytest.raises(ValueError):
        verifier.save_result({"run_id": "../escape"}, tmp_path)
    assert not list(tmp_path.iterdir())


def test_result_redaction_handles_nested_credential_metadata():
    result = verifier._redact({"model": "prefix-" + KEY, "checks": [TOKEN, {"value": KEY}]}, (TOKEN, KEY))
    assert KEY not in json.dumps(result) and TOKEN not in json.dumps(result)


def test_noninteractive_cli_saves_not_configured_result(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SAP_DB", str(tmp_path / "operator.sqlite3"))
    assert verifier.main(["--output-dir", str(tmp_path / "results")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "not_configured" and result["live_verified"] is False
    files = list((tmp_path / "results").glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text()) == result
    assert not (tmp_path / "operator.sqlite3").exists()


def test_configuration_errors_do_not_echo_secret_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SAP_PLANNER_PROVIDER", "openai_compatible")
    monkeypatch.setenv("SAP_PLANNER_MODEL", MODEL)
    monkeypatch.setenv("SAP_PLANNER_API_KEY", KEY)
    monkeypatch.setenv("SAP_PLANNER_BASE_URL", "https://user:" + KEY + "@remote.invalid/v1")
    assert verifier.main(["--output-dir", str(tmp_path)]) == 2
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["status"] == "configuration_error" and result["live_verified"] is False
    assert KEY not in output.out + output.err
    assert KEY not in next(tmp_path.glob("*.json")).read_text()


def test_mistaken_api_key_argument_is_not_echoed(capsys):
    with pytest.raises(SystemExit) as error:
        verifier.main(["--api-key", KEY])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert KEY not in output.err + output.out


def test_interactive_nonterminal_refuses_echo_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(verifier.sys.stdin, "isatty", lambda: False)
    def forbidden_prompt(*args):
        pytest.fail("Do not ask for a key without a secure terminal")
    monkeypatch.setattr(getpass, "getpass", forbidden_prompt)
    assert verifier.main(["--interactive", "--output-dir", str(tmp_path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "configuration_error" and result["failure_code"] == "interactive_unavailable"


def test_interactive_key_is_kept_in_memory_only(monkeypatch):
    monkeypatch.setattr(verifier.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(verifier.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: MODEL)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: KEY)
    result = verifier._settings(True)
    assert result.planner_provider == "openai_compatible" and result.planner_model == MODEL
    assert result.planner_api_key == KEY and "SAP_PLANNER_API_KEY" not in __import__("os").environ
    assert KEY not in repr(result)


def test_hidden_input_warning_does_not_fall_back_to_echo(tmp_path, monkeypatch, capsys):
    import warnings
    monkeypatch.setattr(verifier.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(verifier.sys.stderr, "isatty", lambda: True)
    monkeypatch.setenv("SAP_PLANNER_MODEL", MODEL)
    def unsafe_getpass(prompt):
        warnings.warn("Cannot hide input", getpass.GetPassWarning)
        pytest.fail("Echo fallback must be stopped by the warning")
    monkeypatch.setattr(getpass, "getpass", unsafe_getpass)
    assert verifier.main(["--interactive", "--output-dir", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "configuration_error"


def test_keyless_local_configuration_does_not_prompt_for_key(monkeypatch):
    monkeypatch.setattr(verifier.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(verifier.sys.stderr, "isatty", lambda: True)
    monkeypatch.setenv("SAP_PLANNER_MODEL", MODEL)
    monkeypatch.setenv("SAP_PLANNER_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: pytest.fail("Loopback can be keyless"))
    assert verifier._settings(True).planner_api_key == ""


def test_report_save_failure_is_an_explicit_failure(tmp_path, monkeypatch, capsys):
    def unavailable(*args):
        raise OSError(KEY)
    monkeypatch.setattr(verifier, "save_result", unavailable)
    assert verifier.main(["--output-dir", str(tmp_path)]) == 3
    output = capsys.readouterr()
    assert json.loads(output.out)["report_saved"] is False
    assert KEY not in output.out + output.err and "Unable to save" in output.err


def test_interrupt_does_not_claim_verification_success(tmp_path, monkeypatch, capsys):
    def interrupted(interactive):
        raise KeyboardInterrupt
    monkeypatch.setattr(verifier, "_settings", interrupted)
    assert verifier.main(["--output-dir", str(tmp_path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "interrupted" and result["live_verified"] is False


def test_real_http_contract_fixture_is_still_marked_as_test_transport(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.path, self.headers.get("Authorization"), body))
            data = json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": content()}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = settings(tmp_path, planner_base_url=f"http://127.0.0.1:{server.server_port}/v1")
        result = run(config, OpenAICompatiblePlanner(config))  # Real HTTP, canned fixture output.
        assert result["status"] == "simulated" and result["live_verified"] is False
        assert result["workflow_passed"] is True and result["tool_calls"] == 0
        assert len(requests) == 1 and requests[0][0] == "/v1/chat/completions"
        assert requests[0][1] == "Bearer " + KEY
        assert KEY.encode() not in requests[0][2] and TOKEN.encode() not in requests[0][2]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.parametrize("secret", [KEY, TOKEN])
@pytest.mark.parametrize("field", ["summary", "rationale"])
def test_json_escaped_credentials_cannot_be_persisted(tmp_path, secret, field):
    from fastapi.testclient import TestClient
    from app.main import create_app
    config, calls = settings(tmp_path), []
    data = json.loads(content())
    if field == "summary":
        data["summary"] = secret
    else:
        data["actions"][0]["rationale"] = secret
    escaped = "".join("\\u%04x" % ord(char) for char in secret)
    raw = json.dumps(data).replace(secret, escaped)
    assert secret not in raw
    decoded = json.loads(raw)
    assert (decoded["summary"] if field == "summary" else decoded["actions"][0]["rationale"]) == secret
    app = create_app(config, planner=provider(config, calls, raw=raw), announce_token=False)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as client:
        created = client.post("/api/v1/assessments", json={"name": "Credential echo regression",
                  "targets": list(verifier.TARGETS), "authorization_confirmed": True})
        assessment_id = created.json()["id"]
        response = client.post("/api/v1/assessments/" + assessment_id + "/plans",
                               json={"goal": "Review headers"})
        assert response.status_code == 502
        stored = app.state.store.report(assessment_id)
        assert stored["plans"][0]["error_code"] == "provider_response"
        assert stored["actions"] == [] and len(calls) == 1
        assert secret not in json.dumps(stored)
