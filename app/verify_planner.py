"""Verify configured planner proposals without authorizing or running a scanner."""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4
import warnings
import httpx
from .config import Settings
from .main import create_app
from .planning import ERRORS


TARGETS = ("http://127.0.0.1:8001/vulnerable", "http://127.0.0.1:8001/hardened")
GOAL = "Propose HTTP security-header checks for the authorized demo URLs. Do not execute anything."
DEFAULT_OUTPUT_DIR = Path("data/planner-verifications")
MESSAGES = {
    "not_configured": "Select openai_compatible and configure a model; remote endpoints also need a key. Or run with --interactive in a local terminal.",
    "configuration_error": "Planner configuration is invalid. Check PROVIDER_SETUP.md; no provider request was sent.",
    "interactive_unavailable": "Interactive entry requires a local terminal with hidden key input; alternatively set the documented environment variables.",
    "interrupted": "Verification was interrupted. A provider request may have started; no tools were authorized.",
    "passed": "Configured-endpoint planning passed; proposals stayed pending and no tools ran.",
    "simulated": "Injected test-provider workflow passed. This does not verify a real model.",
    "failed": "Planner verification did not pass. Inspect the trusted failure code; no tools were authorized.",
}


class VerificationFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NoExecutionChecker:
    def __init__(self, result):
        self.calls = 0
        self.result = result

    async def run(self, target):
        self.calls += 1
        self.result["tool_calls"] = self.calls
        raise VerificationFailure("unexpected_tool_execution")


def _require(condition, code):
    if not condition:
        raise VerificationFailure(code)


def _new_result():
    return {"schema_version": 1, "run_id": str(uuid4()),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed", "live_verified": False, "workflow_passed": False,
            "transport": "not_contacted", "scope": list(TARGETS),
            "checks": {}, "tool_calls": 0}


def _redact(value, protected):
    if isinstance(value, str):
        for secret in protected:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, protected) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, protected) for key, item in value.items()}
    return value


async def _workflow(settings, result, planner):
    checker = NoExecutionChecker(result)
    with tempfile.TemporaryDirectory(prefix="honeyagi-verify-") as directory:
        # Never touch the operator's live database or use their dashboard token.
        local = replace(settings, db_path=Path(directory) / "verification.sqlite3",
                        token=secrets.token_urlsafe(32))
        app = create_app(local, checker=checker, planner=planner, announce_token=False)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                         base_url="http://testserver", trust_env=False,
                                         headers={"Authorization": "Bearer " + local.token}) as client:
                info = (await client.get("/api/v1/planner")).json()
                _require(info["mode"] == "llm" and info["provider"] == "openai_compatible"
                         and info["model"] == settings.planner_model and info["requires_approval"] is True,
                         "provider_mode_mismatch")
                result["checks"]["provider_mode"] = True
                response = await client.post("/api/v1/assessments", json={
                    "name": "Planner verification", "targets": list(TARGETS), "authorization_confirmed": True})
                _require(response.status_code == 201, "assessment_creation_failed")
                assessment_id = response.json()["id"]
                root = "/api/v1/assessments/" + assessment_id
                request = {"goal": GOAL, "request_id": str(uuid4())}
                response = await client.post(root + "/plans", json=request)
                result["planning_http_status"] = response.status_code
                if response.status_code != 201:
                    plans = app.state.store.list_plans(assessment_id)
                    code = plans[0]["error_code"] if plans else "planning_failed"
                    raise VerificationFailure(code if code in ERRORS else "planning_failed")
                plan = response.json()
                _require(plan["status"] == "completed" and plan["provider"] == "openai_compatible"
                         and plan["model"] == settings.planner_model, "plan_provenance_mismatch")
                result["checks"]["plan_completed"] = True
                detail = (await client.get(root)).json()
                actions = detail["actions"]
                _require(1 <= len(actions) <= len(TARGETS), "no_useful_proposals")
                _require(all(a["status"] == "pending" and a["evidence"] is None
                             and a["plan_id"] == plan["id"] and a["tool"] == "http_headers"
                             and a["target"] in TARGETS for a in actions), "proposal_boundary_failed")
                result["checks"]["pending_only"] = True
                result["proposal_count"] = len(actions)
                first_id = actions[0]["id"]
                denied = await client.post("/api/v1/actions/" + first_id + "/approve", json={},
                                           headers={"Authorization": ""})
                _require(denied.status_code == 401, "unauthenticated_approval_allowed")
                result["checks"]["unauthenticated_approval_denied"] = True
                for action in actions:
                    denied = await client.post("/api/v1/actions/" + action["id"] + "/execute", json={})
                    _require(denied.status_code == 409, "unapproved_execution_allowed")
                result["checks"]["unapproved_execution_denied"] = True
                replay = await client.post(root + "/plans", json=request)
                _require(replay.status_code == 200 and replay.json() == plan, "replay_mismatch")
                result["checks"]["idempotent_replay"] = True
                final = (await client.get(root)).json()
                _require(all(a["status"] == "pending" and a["evidence"] is None
                             for a in final["actions"]) and len(final["actions"]) == len(actions),
                         "action_state_changed")
                report = (await client.get(root + "/report")).json()
                _require(all(report["integrity"].get(k) is True for k in
                             ("audit_chain_valid", "evidence_hashes_valid", "plan_hashes_valid")),
                         "report_integrity_failed")
                result["checks"]["report_integrity"] = True
                result["plan_id"], result["plan_sha256"] = plan["id"], plan["sha256"]
                _require(checker.calls == 0, "unexpected_tool_execution")
                result["checks"]["zero_tool_calls"] = True
    result["tool_calls"] = checker.calls


async def verify(settings, *, test_planner=None):
    """Injected providers are always labelled simulated and cannot mark live verification."""
    started = time.monotonic()
    result = _new_result()
    result.update(provider=settings.planner_provider, model=settings.planner_model)
    if settings.planner_provider != "openai_compatible":
        result["status"] = "not_configured"
    else:
        result["transport"] = "injected_test_provider" if test_planner is not None else "configured_endpoint"
        try:
            await _workflow(settings, result, test_planner)
            result["workflow_passed"] = True
            result["live_verified"] = test_planner is None
            result["status"] = "passed" if result["live_verified"] else "simulated"
        except VerificationFailure as error:
            result["failure_code"] = error.code
        except Exception:
            # Never serialize exception messages, upstream text, or configuration values.
            result["failure_code"] = "verification_internal_error"
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["message"] = MESSAGES[result["status"]]
    return _redact(result, (settings.token, settings.planner_api_key))


def _settings(interactive):
    if not interactive:
        return Settings(token=secrets.token_urlsafe(32))
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise VerificationFailure("interactive_unavailable")
    model = os.getenv("SAP_PLANNER_MODEL") or input("Model ID: ").strip()
    base_url = os.getenv("SAP_PLANNER_BASE_URL", "https://api.openai.com/v1")
    # Keyless local inference remains supported; only the operator configures the endpoint.
    loopback = urlsplit(base_url).hostname in ("127.0.0.1", "localhost", "::1")
    key = os.getenv("SAP_PLANNER_API_KEY", "")
    if not key and not loopback:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Planner API key (hidden): ")
    return Settings(token=secrets.token_urlsafe(32), planner_provider="openai_compatible",
                    planner_model=model, planner_base_url=base_url, planner_api_key=key)


def save_result(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # A unique, exclusively created file preserves earlier successes and failures.
    path = directory / (str(UUID(result["run_id"])) + ".json")
    with path.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=True, indent=2)
        file.write("\n")
    return path


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # A mistaken --api-key argument must not be echoed back with its value.
        self.exit(2, "Invalid arguments. Use --help; credentials belong in environment variables or hidden interactive input.\n")


def main(argv=None):
    parser = SafeArgumentParser(description="Verify one configured model plan; never approve or run a tool.")
    parser.add_argument("--interactive", action="store_true", help="Prompt locally for a model and, if needed, a hidden API key")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="Directory for a unique JSON result (default: data/planner-verifications)")
    args = parser.parse_args(argv)
    try:
        settings = _settings(args.interactive)
        result = asyncio.run(verify(settings))
    except (KeyboardInterrupt, EOFError):
        result = _new_result()
        result["status"] = "interrupted"
        result["message"] = MESSAGES["interrupted"]
    except VerificationFailure as error:
        result = _new_result()
        result["status"] = "configuration_error"
        result["failure_code"] = error.code
        result["message"] = MESSAGES.get(error.code, MESSAGES["configuration_error"])
    except (ValueError, OSError, getpass.GetPassWarning):
        result = _new_result()
        result["status"] = "configuration_error"
        result["message"] = MESSAGES["configuration_error"]
    result.setdefault("finished_at", datetime.now(timezone.utc).isoformat())
    try:
        save_result(result, args.output_dir)
    except OSError:
        result["report_saved"] = False
        print(json.dumps(result, ensure_ascii=True, indent=2))
        print("Unable to save the verification result. Check output directory access.", file=sys.stderr)
        return 3
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["live_verified"] else (2 if result["status"] in
            ("not_configured", "configuration_error", "interrupted") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
