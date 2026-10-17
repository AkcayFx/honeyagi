"""Bounded, typed observations for planning; raw target text never crosses this boundary."""
import json
import re
from dataclasses import asdict, dataclass
from uuid import UUID
from .policy import validate_action, PolicyError

MAX_OBSERVATIONS = 3
MAX_CONTEXT_BYTES = 4096


class EvidenceContextError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceSummary:
    evidence_id: str
    sha256: str
    target: str
    status_code: int
    conclusion: str
    csp_present: bool | None
    nosniff_valid: bool | None
    referrer_policy_present: bool | None


@dataclass(frozen=True)
class EvidenceContext:
    observations: tuple[EvidenceSummary, ...]
    omitted_count: int
    schema_version: int = 1

    @classmethod
    def from_dict(cls, value):
        return cls(tuple(EvidenceSummary(**item) for item in value["observations"]),
                   value["omitted_count"], value["schema_version"])


def _summary(action, targets, demo_origin):
    evidence = action["evidence"]
    validate_action(action["tool"], action["target"], targets, demo_origin)
    if (str(UUID(action["id"])) != action["id"] or
            not isinstance(evidence, dict) or evidence.get("method") != "GET" or
            evidence.get("target") != action["target"] or
            not isinstance(evidence.get("sha256"), str) or
            not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])):
        raise EvidenceContextError()
    status = evidence["status_code"]
    headers = evidence["headers"]
    if type(status) is not int or not 100 <= status <= 599 or not isinstance(headers, dict):
        raise EvidenceContextError()
    names = ("content-security-policy", "x-content-type-options", "referrer-policy")
    for name in names:
        if name in headers and (not isinstance(headers[name], str) or len(headers[name]) > 4096):
            raise EvidenceContextError()
    observed = 200 <= status < 300
    # Derive only structural observations. Do not copy stored finding/conclusion text.
    return EvidenceSummary(
        action["id"], evidence["sha256"], action["target"], status,
        "observed" if observed else "inconclusive",
        bool(headers.get(names[0], "").strip()) if observed else None,
        headers.get(names[1], "").strip().lower() == "nosniff" if observed else None,
        bool(headers.get(names[2], "").strip()) if observed else None,
    )


def build_evidence_context(report, demo_origin):
    """Latest completed check per URL, ordered by completion, from a verified snapshot."""
    try:
        if not report or not all(report["integrity"][key] is True for key in (
                "audit_chain_valid", "evidence_hashes_valid", "plan_hashes_valid")):
            raise EvidenceContextError()
        actions = {a["id"]: a for a in report["actions"] if a["status"] == "completed"}
        order = [e["action_id"] for e in report["audit"] if e["event"] == "execution_completed"]
        if set(order) != set(actions) or len(order) != len(set(order)):
            raise EvidenceContextError()
        selected, seen = [], set()
        for action_id in reversed(order):
            action = actions[action_id]
            item = _summary(action, report["assessment"]["targets"], demo_origin)
            key = (action["tool"], action["target"])
            if key not in seen and len(selected) < MAX_OBSERVATIONS:
                selected.append(item)
            seen.add(key)
        while True:
            result = EvidenceContext(tuple(selected), len(order) - len(selected))
            size = len(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")).encode())
            if size <= MAX_CONTEXT_BYTES:
                return result
            if not selected:
                raise EvidenceContextError()
            selected.pop()
    except (KeyError, TypeError, ValueError, AttributeError, PolicyError, RecursionError) as exc:
        raise EvidenceContextError("Evidence cannot be safely summarized") from exc
