import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
import httpx
from fastapi.testclient import TestClient
from app.db import Store, digest, ExecutionBusy
from app.main import create_app
from app.tools import HeaderChecker, analyse, compare
from conftest import TOKEN, ORIGIN, assessment, proposal, completed


def test_end_to_end_evidence_audit_and_report(lab):
    c, store, calls, _ = lab
    a = assessment(c)
    result = completed(c, proposal(c, a["id"]))
    evidence = result["evidence"]
    assert len(evidence["findings"]) == 3
    assert calls == [ORIGIN + "/vulnerable"]
    assert "private-secret" not in json.dumps(evidence)
    assert "private-server" not in json.dumps(evidence)
    assert "body-secret" not in json.dumps(evidence)
    assert digest({k: v for k, v in evidence.items() if k != "sha256"}) == evidence["sha256"]
    report = c.get(f'/api/v1/assessments/{a["id"]}/report')
    assert "attachment" in report.headers["content-disposition"]
    assert report.json()["integrity"]["audit_chain_valid"]
    assert report.json()["integrity"]["evidence_hashes_valid"]
    assert [x["event"] for x in report.json()["audit"]] == ["assessment_created", "action_proposed", "action_approved", "execution_started", "execution_completed"]


def test_hardened_no_observations(lab):
    c, *_ = lab
    result = completed(c, proposal(c, assessment(c)["id"], ORIGIN + "/hardened"))
    assert result["evidence"]["findings"] == []


def test_redirect_never_followed(lab):
    c, _, calls, _ = lab
    result = completed(c, proposal(c, assessment(c)["id"], ORIGIN + "/redirect"))
    assert calls == [ORIGIN + "/redirect"]
    assert result["evidence"]["status_code"] == 302
    assert result["evidence"]["conclusion"].startswith("inconclusive")
    assert result["evidence"]["findings"] == []


def test_approval_required_and_execution_is_single_use(lab):
    c, _, calls, _ = lab
    action = proposal(c, assessment(c)["id"])
    root = "/api/v1/actions/" + action["id"]
    assert c.post(root + "/execute", json={}).status_code == 409
    assert calls == []
    completed(c, action)
    assert c.post(root + "/execute", json={}).status_code == 409
    assert c.post(root + "/approve", json={}).status_code == 409
    assert len(calls) == 1


def test_reject_is_terminal(lab):
    c, _, calls, _ = lab
    action = proposal(c, assessment(c)["id"])
    root = "/api/v1/actions/" + action["id"]
    assert c.post(root + "/reject", json={"note": "Not needed"}).json()["status"] == "rejected"
    for transition in ("approve", "execute", "retest"):
        assert c.post(root + "/" + transition, json={}).status_code == 409
    assert calls == []


def test_retest_creates_pending_action_and_compares(lab):
    c, *_ = lab
    original = completed(c, proposal(c, assessment(c)["id"]))
    retest = c.post('/api/v1/actions/' + original["id"] + '/retest', json={}).json()
    assert retest["status"] == "pending" and retest["parent_id"] == original["id"]
    result = completed(c, retest)
    assert len(result["evidence"]["comparison"]["still_observed"]) == 3
    assert result["evidence"]["comparison"]["no_longer_observed"] == []


def test_scope_denial_is_audited(lab):
    c, store, calls, _ = lab
    a = assessment(c, [ORIGIN + "/vulnerable"])
    denied = c.post(f'/api/v1/assessments/{a["id"]}/actions', json={"tool": "http_headers", "target": ORIGIN + "/hardened", "rationale": "Out of scope"})
    assert denied.status_code == 403
    assert store.report(a["id"])["audit"][-1]["event"] == "policy_denied"
    assert calls == []


def test_revalidation_before_execution(lab):
    c, store, calls, _ = lab
    a = assessment(c)
    action = proposal(c, a["id"])
    root = "/api/v1/actions/" + action["id"]
    c.post(root + "/approve", json={})
    with store.connection(write=True) as db:
        db.execute("UPDATE actions SET target='http://example.com' WHERE id=?", (action["id"],))
    assert c.post(root + "/execute", json={}).status_code == 403
    assert calls == []


def test_restart_recovers_inflight_and_preserves_data(lab):
    c, store, _, settings = lab
    a = assessment(c)
    action = proposal(c, a["id"])
    store.transition(action["id"], "pending", "approved", "action_approved")
    store.transition(action["id"], "approved", "running", "execution_started")
    with TestClient(create_app(settings), headers={"Authorization": "Bearer " + TOKEN}) as restarted:
        recovered = restarted.get(f'/api/v1/assessments/{a["id"]}').json()
        assert recovered["actions"][0]["status"] == "failed"
        assert "restart" in recovered["actions"][0]["error"]
        assert store.report(a["id"])["audit"][-1]["event"] == "execution_interrupted"


def test_atomic_claim_with_concurrent_callers(lab):
    c, store, *_ = lab
    action = proposal(c, assessment(c)["id"])
    store.transition(action["id"], "pending", "approved", "action_approved")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.transition(action["id"], "approved", "running", "execution_started"), range(2)))
    assert sorted(results) == [False, True]


def test_concurrency_limit(lab):
    c, store, *_ = lab
    a = assessment(c)
    for _ in range(2):
        action = proposal(c, a["id"])
        store.transition(action["id"], "pending", "approved", "action_approved")
        store.transition(action["id"], "approved", "running", "execution_started")
    third = proposal(c, a["id"])
    c.post('/api/v1/actions/' + third["id"] + '/approve', json={})
    assert c.post('/api/v1/actions/' + third["id"] + '/execute', json={}).status_code == 429
    assert store.get_action(third["id"])["status"] == "approved"


def test_evidence_and_audit_tamper_detection(lab):
    c, store, *_ = lab
    a = assessment(c)
    action = completed(c, proposal(c, a["id"]))
    evidence = action["evidence"]
    evidence["status_code"] = 500
    evidence["sha256"] = digest({k: v for k, v in evidence.items() if k != "sha256"})
    with store.connection(write=True) as db:
        db.execute("UPDATE actions SET evidence=? WHERE id=?", (json.dumps(evidence), action["id"]))
    assert not store.report(a["id"])["integrity"]["evidence_hashes_valid"]
    with store.connection(write=True) as db:
        db.execute("UPDATE audit SET event='rewritten' WHERE assessment_id=? AND event='action_approved'", (a["id"],))
    assert not store.report(a["id"])["integrity"]["audit_chain_valid"]


def test_network_failure_cannot_replay(lab):
    c, store, _, settings = lab
    def unavailable(request):
        raise httpx.ConnectError("secret-network-detail", request=request)
    with TestClient(create_app(settings, HeaderChecker(transport=httpx.MockTransport(unavailable))), headers={"Authorization": "Bearer " + TOKEN}) as failing:
        action = proposal(failing, assessment(failing)["id"])
        root = '/api/v1/actions/' + action["id"]
        failing.post(root + '/approve', json={})
        result = failing.post(root + '/execute', json={}).json()
        assert result["status"] == "failed"
        assert "secret-network-detail" not in json.dumps(result)
        assert failing.post(root + '/execute', json={}).status_code == 409
        assert failing.post(root + '/retest', json={}).status_code == 201


def test_total_timeout():
    async def slow(request):
        await asyncio.sleep(.1)
        return httpx.Response(200)
    checker = HeaderChecker(timeout=.01, transport=httpx.MockTransport(slow))
    try:
        asyncio.run(checker.run(ORIGIN + '/vulnerable'))
        assert False, "Expected a wall-clock timeout"
    except TimeoutError:
        pass


def test_oversized_headers_fail():
    checker = HeaderChecker(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"x-large": "a" * 40000})))
    try:
        asyncio.run(checker.run(ORIGIN + '/vulnerable'))
        assert False, "Expected bounded-header rejection"
    except ValueError:
        pass


def test_nosniff_value_and_error_responses():
    assert any(f["id"] == "x-content-type-options" for f in analyse(200, {"x-content-type-options": "invalid"})[0])
    assert not any(f["id"] == "x-content-type-options" for f in analyse(200, {"x-content-type-options": "NOSNIFF"})[0])
    assert analyse(404, {})[0] == []


def test_comparison_not_claiming_fix_on_failed_response():
    assert compare({"conclusion": "observed", "findings": [{"id": "x"}]}, {"conclusion": "inconclusive", "findings": []})["result"] == "inconclusive"
    assert compare({"conclusion": "observed", "findings": [{"id": "x"}]}, {"conclusion": "observed", "findings": []})["no_longer_observed"] == ["x"]
