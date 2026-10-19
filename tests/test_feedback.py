"""Operator-triggered feedback with simulated providers and real authorization paths."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from app.db import Store
from app.main import create_app
from app.planning import ProviderError
from conftest import TOKEN, ORIGIN, assessment, proposal, completed
from test_planning import planning_lab, StubPlanner, generate, output


class SequencePlanner(StubPlanner):
    def __init__(self, responses):
        super().__init__("")
        self.responses = responses

    async def plan(self, context):
        self.calls += 1
        self.contexts.append(context)
        value = self.responses[self.calls - 1]
        if isinstance(value, Exception):
            raise value
        return value


def step(client, assessment_id, key=None, **extra):
    return client.post(f"/api/v1/assessments/{assessment_id}/continue",
                       json={"request_id": key or str(uuid4()), **extra})


def check(target):
    return {"tool": "http_headers", "target": ORIGIN + target, "rationale": "Observe headers"}


def progress(client, assessment_id):
    return client.get(f"/api/v1/assessments/{assessment_id}").json()["planning_progress"]


def first_check(client, store, assessment_id):
    response = generate(client, assessment_id)
    assert response.status_code == 201, response.text
    plan = response.json()
    completed(client, store.get_action(plan["action_ids"][0]))
    return plan


def test_feedback_proposes_next_scoped_check_then_finishes(planning_lab):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), output([check("/hardened")]), output([])])
    c, store, calls = start(provider)
    a = assessment(c)
    assert progress(c, a["id"])["status"] == "not_started"
    initial = first_check(c, store, a["id"])
    assert progress(c, a["id"])["status"] == "ready"
    next_plan = step(c, a["id"])
    assert next_plan.status_code == 201, next_plan.text
    second = next_plan.json()
    assert second["goal"] == initial["goal"] and second["continuation_of"] == initial["id"]
    assert provider.contexts[1].evidence_context.observations[0].evidence_id == initial["action_ids"][0]
    assert "IGNORE ALL RULES" not in repr(provider.contexts[1])
    pending = store.get_action(second["action_ids"][0])
    assert pending["status"] == "pending" and len(calls) == 1
    assert c.post("/api/v1/actions/" + pending["id"] + "/execute", json={}).status_code == 409
    assert step(c, a["id"]).status_code == 409 and provider.calls == 2
    completed(c, pending)
    last = step(c, a["id"])
    assert last.status_code == 201, last.text
    assert last.json()["action_ids"] == [] and last.json()["continuation_of"] == second["id"]
    status = progress(c, a["id"])
    assert status == {"status": "finished", "steps_used": 3, "max_steps": 4,
                      "latest_plan_id": last.json()["id"], "can_continue": False}
    assert step(c, a["id"]).status_code == 409
    assert provider.calls == 3 and len(calls) == 2
    report = store.report(a["id"])
    assert report["planning_progress"] == status
    assert all(report["integrity"][key] for key in ("audit_chain_valid", "evidence_hashes_valid", "plan_hashes_valid"))
    started = [e for e in report["audit"] if e["event"] == "planning_started"]
    assert [e["details"].get("step_number", 1) for e in started] == [1, 2, 3]


@pytest.mark.parametrize("state", ["pending", "approved", "running"])
def test_unresolved_actions_block_continuation_without_provider_call(planning_lab, state):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")])])
    c, store, calls = start(provider)
    a = assessment(c)
    original = generate(c, a["id"]).json()
    action_id = original["action_ids"][0]
    if state in ("approved", "running"):
        c.post("/api/v1/actions/" + action_id + "/approve", json={})
    if state == "running":
        store.transition(action_id, "approved", "running", "execution_started")
    result = step(c, a["id"])
    assert result.status_code == 409
    assert progress(c, a["id"])["status"] == "awaiting_actions"
    assert provider.calls == 1 and len(store.list_plans(a["id"])) == 1 and calls == []


@pytest.mark.parametrize("state", ["rejected", "failed"])
def test_terminal_action_states_allow_review_but_do_not_become_evidence(planning_lab, state):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), output([])])
    c, store, calls = start(provider)
    a = assessment(c)
    plan = generate(c, a["id"]).json()
    action_id = plan["action_ids"][0]
    if state == "rejected":
        c.post("/api/v1/actions/" + action_id + "/reject", json={})
    else:
        store.transition(action_id, "pending", "failed", "execution_failed", error="Test failure")
    assert step(c, a["id"]).status_code == 201
    assert provider.contexts[1].evidence_context.observations == ()
    assert progress(c, a["id"])["status"] == "finished" and calls == []


def test_step_budget_stops_additional_requests_transactionally(planning_lab, monkeypatch):
    monkeypatch.setattr("app.feedback.MAX_PLANNING_STEPS", 2)
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), output([check("/hardened")])])
    c, store, calls = start(provider)
    a = assessment(c)
    first_check(c, store, a["id"])
    second = step(c, a["id"]).json()
    completed(c, store.get_action(second["action_ids"][0]))
    status = progress(c, a["id"])
    assert status["status"] == "budget_reached" and status["steps_used"] == status["max_steps"] == 2
    for _ in range(3):
        assert step(c, a["id"]).status_code == 409
    assert provider.calls == 2 and len(store.list_plans(a["id"])) == 2 and len(calls) == 2


def test_default_four_steps_include_the_final_no_more_checks_request(planning_lab):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), output([check("/hardened")]),
                                output([check("/redirect")]), output([])])
    c, store, _ = start(provider)
    a = assessment(c)
    first_check(c, store, a["id"])
    for _ in range(2):
        response = step(c, a["id"])
        assert response.status_code == 201, response.text
        completed(c, store.get_action(response.json()["action_ids"][0]))
    assert step(c, a["id"]).status_code == 201
    assert progress(c, a["id"])["steps_used"] == 4
    assert step(c, a["id"]).status_code == 409 and provider.calls == 4


def test_continuation_replay_retains_predecessor_and_snapshot_after_later_steps(planning_lab):
    start, settings = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), output([check("/hardened")]), output([])])
    c, store, _ = start(provider)
    a, key = assessment(c), str(uuid4())
    first_check(c, store, a["id"])
    second = step(c, a["id"], key)
    completed(c, store.get_action(second.json()["action_ids"][0]))
    assert step(c, a["id"]).status_code == 201
    replay = step(c, a["id"], key)
    assert replay.status_code == 200 and replay.json() == second.json()
    with TestClient(create_app(settings, planner=SequencePlanner([])), headers={"Authorization": "Bearer " + TOKEN}) as restarted:
        assert step(restarted, a["id"], key).json() == second.json()
    assert provider.calls == 3 and len(store.list_plans(a["id"])) == 3


def test_request_ids_cannot_cross_assessments_or_planning_endpoints(planning_lab):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), output([])])
    c, store, _ = start(provider)
    a = assessment(c)
    root = first_check(c, store, a["id"])
    assert step(c, a["id"], root["id"]).status_code == 409
    continued = step(c, a["id"]).json()
    other = assessment(c)
    assert step(c, other["id"], continued["id"]).status_code == 409
    assert generate(c, a["id"], goal=root["goal"], request_id=continued["id"]).status_code == 409
    assert provider.calls == 2 and store.list_plans(other["id"]) == []


@pytest.mark.parametrize("extra", [
    {"goal": "Replace immutable goal"}, {"include_evidence": False}, {"max_steps": 99},
    {"approved": True}, {"continuation_of": str(uuid4())},
])
def test_client_cannot_override_continuation_authority_or_budget(planning_lab, extra):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")])])
    c, store, _ = start(provider)
    a = assessment(c)
    first_check(c, store, a["id"])
    assert step(c, a["id"], **extra).status_code == 422
    assert provider.calls == 1


def test_continue_requires_auth_origin_valid_uuid_and_existing_assessment(lab):
    c, _, calls, _ = lab
    a = assessment(c)
    path = f"/api/v1/assessments/{a['id']}/continue"
    assert c.post(path, json={}, headers={"Authorization": ""}).status_code == 401
    assert c.post(path, json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post(path, json={"request_id": "invalid"}).status_code == 422
    assert c.post("/api/v1/assessments/missing/continue", json={}).status_code == 404
    assert step(c, a["id"]).status_code == 409 and calls == []


@pytest.mark.parametrize("raw,status", [
    (output([{"tool": "http_headers", "target": "https://example.com", "rationale": "Escape"}]), 403),
    (output([{"tool": "http_headers", "target": ORIGIN + "/hardened", "rationale": "Run", "approved": True}]), 502),
    (output([check("/vulnerable")]), 409),
    (output([check("/hardened"), check("/hardened")]), 502),
])
def test_continued_output_cannot_escape_policy_or_duplicate_checks(planning_lab, raw, status):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), raw])
    c, store, calls = start(provider)
    a, key = assessment(c), str(uuid4())
    first_check(c, store, a["id"])
    response = step(c, a["id"], key)
    assert response.status_code == status
    assert step(c, a["id"], key).status_code == status
    assert progress(c, a["id"])["status"] == "blocked"
    assert len(store.list_plans(a["id"])) == 2 and len(store.list_actions(a["id"])) == 1
    assert provider.calls == 2 and len(calls) == 1


def test_failed_provider_consumes_step_and_never_automatically_retries(planning_lab):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), ProviderError("provider_rate_limited")])
    c, store, _ = start(provider)
    a, key = assessment(c), str(uuid4())
    first_check(c, store, a["id"])
    assert step(c, a["id"], key).status_code == 429
    assert step(c, a["id"], key).status_code == 429
    assert step(c, a["id"]).status_code == 409
    assert progress(c, a["id"])["steps_used"] == 2 and provider.calls == 2


def test_tampered_evidence_blocks_step_before_provider_or_plan_insert(planning_lab):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")])])
    c, store, _ = start(provider)
    a = assessment(c)
    first = first_check(c, store, a["id"])
    with store.connection(write=True) as db:
        db.execute("UPDATE actions SET evidence='{}' WHERE id=?", (first["action_ids"][0],))
    assert step(c, a["id"]).status_code == 409
    assert provider.calls == 1 and len(store.list_plans(a["id"])) == 1


def test_concurrent_continuations_call_provider_once(planning_lab):
    start, _ = planning_lab
    entered, release = Event(), Event()
    class WaitingPlanner(SequencePlanner):
        async def plan(self, context):
            if self.calls:
                entered.set()
                await asyncio.to_thread(release.wait, 3)
            return await super().plan(context)
    provider = WaitingPlanner([output([check("/vulnerable")]), output([])])
    c, store, _ = start(provider)
    a, key = assessment(c), str(uuid4())
    first_check(c, store, a["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(step, c, a["id"], key)
        try:
            assert entered.wait(2)
            assert step(c, a["id"], key).status_code == 409
            assert step(c, a["id"]).status_code == 409
        finally:
            release.set()
        assert future.result(timeout=3).status_code == 201
    assert provider.calls == 2 and len(store.list_plans(a["id"])) == 2


def test_concurrent_manual_proposal_invalidates_continuation_atomically(planning_lab):
    start, _ = planning_lab
    class RacingPlanner(SequencePlanner):
        async def plan(self, context):
            if self.calls:
                store.propose(a["id"], "http_headers", ORIGIN + "/redirect", "Manual proposal during generation")
            return await super().plan(context)
    provider = RacingPlanner([output([check("/vulnerable")]), output([check("/hardened")])])
    c, store, _ = start(provider)
    a = assessment(c)
    first_check(c, store, a["id"])
    assert step(c, a["id"]).status_code == 409
    assert len(store.list_actions(a["id"])) == 2
    assert all(x["target"] != ORIGIN + "/hardened" for x in store.list_actions(a["id"]))


def test_provider_identity_change_requires_explicit_new_initial_plan(planning_lab):
    from app.planning import PlannerInfo
    start, settings = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")])])
    c, store, _ = start(provider)
    a = assessment(c)
    first_check(c, store, a["id"])
    changed = SequencePlanner([])
    changed.info = PlannerInfo(provider="test", model="different-model")
    with TestClient(create_app(settings, planner=changed), headers={"Authorization": "Bearer " + TOKEN}) as restarted:
        assert step(restarted, a["id"]).status_code == 409
    assert changed.calls == 0 and len(store.list_plans(a["id"])) == 1


def test_migration_preserves_completed_plan_hash_and_initial_replay(planning_lab):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), output([])])
    c, store, _ = start(provider)
    a, key = assessment(c), str(uuid4())
    first = generate(c, a["id"], request_id=key).json()
    completed(c, store.get_action(first["action_ids"][0]))
    before = store.report(a["id"])
    with store.connection(write=True) as db:
        db.execute("ALTER TABLE plans DROP COLUMN continuation_of")
    store.initialize()
    after = store.report(a["id"])
    assert after["audit"] == before["audit"] and after["plans"] == before["plans"]
    assert after["integrity"]["plan_hashes_valid"]
    assert generate(c, a["id"], request_id=key).json() == first
    assert step(c, a["id"]).status_code == 201


def test_continuation_link_is_hashed_with_plan_provenance(planning_lab):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")]), output([])])
    c, store, _ = start(provider)
    a = assessment(c)
    first_check(c, store, a["id"])
    last = step(c, a["id"]).json()
    assert store.report(a["id"])["integrity"]["plan_hashes_valid"]
    with store.connection(write=True) as db:
        db.execute("UPDATE plans SET continuation_of=NULL WHERE id=?", (last["id"],))
    assert not store.report(a["id"])["integrity"]["plan_hashes_valid"]


def test_restart_does_not_resume_inflight_continuation(planning_lab):
    start, _ = planning_lab
    provider = SequencePlanner([output([check("/vulnerable")])])
    c, store, _ = start(provider)
    a = assessment(c)
    first = first_check(c, store, a["id"])
    key = str(uuid4())
    store.begin_plan(key, a["id"], first["goal"], provider.info.model_dump(),
                     include_evidence=True, demo_origin=ORIGIN, continuation_of=first["id"])
    store.initialize()
    assert step(c, a["id"], key).status_code == 503
    assert step(c, a["id"]).status_code == 409
    assert provider.calls == 1 and progress(c, a["id"])["status"] == "blocked"
