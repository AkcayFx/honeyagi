"""Planning proposes actions; only the existing operator endpoints may approve/run."""
import asyncio
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4
from pydantic import Field, ValidationError, field_validator
from .models import StrictModel, ProposalInput
from .policy import PolicyError, validate_action


class PlanInput(StrictModel):
    goal: str = Field(min_length=1, max_length=1000)
    request_id: UUID = Field(default_factory=uuid4)

    @field_validator("goal")
    @classmethod
    def safe_text(cls, value):
        if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise ValueError("Goal contains control characters")
        return value


class PlanOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=1000)
    actions: list[ProposalInput] = Field(max_length=8)


class PlannerInfo(StrictModel):
    provider: str = Field(pattern=r"^[a-z0-9._-]{1,64}$")
    model: str = Field(pattern=r"^[a-zA-Z0-9._/-]{1,100}$")


@dataclass(frozen=True)
class PlanningContext:
    """Only purpose and immutable scope: no token, database, HTTP client or raw evidence."""
    goal: str
    targets: tuple[str, ...]
    existing_checks: tuple[tuple[str, str], ...]
    allowed_tools: tuple[str, ...] = ("http_headers",)


class Planner(Protocol):
    info: PlannerInfo

    async def plan(self, context: PlanningContext) -> str: ...


class FakePlanner:
    """Deterministic baseline provider; intentionally not an LLM."""
    info = PlannerInfo(provider="fake", model="header-baseline-v1")

    async def plan(self, context: PlanningContext) -> str:
        covered = set(context.existing_checks)
        targets = [t for t in context.targets if ("http_headers", t) not in covered]
        summary = (f"Propose a security-header baseline for {len(targets)} unchecked scoped URLs. "
                   "This rule-based provider supports header baselines only; every check needs operator review.")
        if not targets:
            summary = "All scoped URLs already have header-check actions. Review those actions or explicitly propose a retest."
        return json.dumps({"summary": summary, "actions": [
            {"tool": "http_headers", "target": target,
             "rationale": "Observe CSP, MIME-sniffing protection and Referrer-Policy on this scoped URL."}
            for target in targets]})


class PlanningError(Exception):
    def __init__(self, status_code, message, plan_id=None):
        self.status_code, self.message, self.plan_id = status_code, message, plan_id


ERRORS = {
    "schema_denied": (502, "Planner output failed schema validation; no actions were created"),
    "scope_denied": (403, "Planner proposed an out-of-scope action; no actions were created"),
    "duplicate_denied": (502, "Planner returned duplicate checks; no actions were created"),
    "stale_plan": (409, "A proposed check already exists; generate a fresh plan"),
    "provider_failed": (503, "Planner unavailable; no actions were created"),
    "timeout": (504, "Planner exceeded its time limit; no actions were created"),
    "interrupted": (503, "Planning was interrupted; generate a new plan"),
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def parse_output(raw, context, demo_origin):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384:
        raise ValueError("Planner output must be bounded JSON text")
    data = json.loads(raw, object_pairs_hook=_unique_object)
    output = PlanOutput.model_validate(data, strict=True)
    seen = set()
    for action in output.actions:
        validate_action(action.tool, action.target, list(context.targets), demo_origin)
        key = (action.tool, action.target)
        if key in seen:
            raise PlanningError(*ERRORS["duplicate_denied"])
        seen.add(key)
    return output


class PlanningService:
    def __init__(self, store, provider, settings):
        self.store, self.provider, self.settings = store, provider, settings
        # Copy provenance at the trusted boundary; provider output cannot replace it.
        self.info = PlannerInfo.model_validate(provider.info.model_dump(), strict=True)

    async def generate(self, assessment_id, request):
        from .db import PlanningBusy, PlanConflict, PlanStale
        plan_id = str(request.request_id)
        try:
            record, created = self.store.begin_plan(plan_id, assessment_id, request.goal, self.info.model_dump())
        except PlanningBusy as exc:
            raise PlanningError(429, "A plan is already running for this assessment, or two planners are busy") from exc
        except PlanConflict as exc:
            raise PlanningError(409, "Request ID is already associated with another goal or assessment") from exc
        if not created:
            if record["status"] == "running":
                raise PlanningError(409, "This planning request is still running", plan_id)
            if record["status"] != "completed":
                raise PlanningError(*ERRORS[record["error_code"]], plan_id)
            return record, False
        assessment = self.store.get_assessment(assessment_id)
        existing = self.store.list_actions(assessment_id)
        context = PlanningContext(request.goal, tuple(assessment["targets"]),
                                  tuple((a["tool"], a["target"]) for a in existing))
        try:
            raw = await asyncio.wait_for(self.provider.plan(context), self.settings.planner_timeout)
            try:
                output = parse_output(raw, context, self.settings.demo_origin)
            except PolicyError:
                return self._deny(plan_id, "scope_denied")
            except PlanningError:
                return self._deny(plan_id, "duplicate_denied")
            except (ValueError, ValidationError, TypeError, RecursionError):
                return self._deny(plan_id, "schema_denied")
            try:
                return self.store.complete_plan(plan_id, output, self.settings.demo_origin), True
            except PlanStale:
                return self._deny(plan_id, "stale_plan")
            except PolicyError:
                return self._deny(plan_id, "scope_denied")
        except PlanningError:
            raise
        except TimeoutError:
            return self._deny(plan_id, "timeout", status="failed")
        except asyncio.CancelledError:
            self.store.fail_plan(plan_id, "interrupted", "failed")
            raise
        except Exception:
            # Neither provider exceptions nor raw output are persisted or returned.
            return self._deny(plan_id, "provider_failed", status="failed")

    def _deny(self, plan_id, code, status="denied"):
        self.store.fail_plan(plan_id, code, status)
        raise PlanningError(*ERRORS[code], plan_id)
