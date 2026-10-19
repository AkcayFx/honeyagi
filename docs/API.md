# Local API

Base: `http://127.0.0.1:8000/api/v1`. All API endpoints require `Authorization: Bearer <terminal token>`. Mutations require `Content-Type: application/json`, including `{}` for decisions without a note. The local dashboard handles these headers automatically.

| Method | Path | Result |
| --- | --- | --- |
| GET | `/assessments` | List assessments |
| POST | `/assessments` | Create immutable scope |
| GET | `/assessments/{id}` | Assessment and action queue |
| GET | `/planner` | Provider identity and the configured planning mode (not a successful-live-call claim) |
| POST | `/assessments/{id}/plans` | Generate a validated plan with pending proposals |
| POST | `/assessments/{id}/continue` | Continue the latest planning sequence with compact evidence |
| POST | `/assessments/{id}/actions` | Create a pending proposal |
| POST | `/actions/{id}/approve` | Approve a pending action |
| POST | `/actions/{id}/reject` | Reject a pending action |
| POST | `/actions/{id}/execute` | Run an approved action once |
| POST | `/actions/{id}/retest` | New pending action for a completed/failed action |
| GET | `/assessments/{id}/report` | Download evidence and audit JSON |

`GET /health` is outside the `/api/v1` prefix and is public. It contains only readiness/version information. Interactive API docs are disabled in this local build.

## Example using Python

With the launcher running in another terminal:

```python
import getpass
import httpx

token = getpass.getpass("Token from server terminal: ")
with httpx.Client(base_url="http://127.0.0.1:8000/api/v1",
                  headers={"Authorization": f"Bearer {token}"},
                  trust_env=False, timeout=35) as client:
    def post(path, data):
        response = client.post(path, json=data)
        response.raise_for_status()
        return response.json()

    assessment = post("/assessments", {
        "name": "Baseline",
        "targets": ["http://127.0.0.1:8001/vulnerable"],
        "authorization_confirmed": True,
    })
    action = post(f"/assessments/{assessment['id']}/actions", {
        "tool": "http_headers",
        "target": "http://127.0.0.1:8001/vulnerable",
        "rationale": "Observe security header configuration",
    })
    # Operator review occurs here. Creating a proposal does not execute it.
    post(f"/actions/{action['id']}/approve", {"note": "Reviewed local scope"})
    result = post(f"/actions/{action['id']}/execute", {})
    print(result["status"], result["evidence"]["findings"])
```

Expected errors: 401 missing/wrong token; 403 origin or policy denial; 404 unknown ID; 409 invalid transition/replay; 413 body too large; 415 wrong mutation content type; 422 invalid schema; 429 two executions already running. A normal network failure returns a stored action with `status: failed` and an audited generic error. It cannot be replayed; propose and approve a retest.

## Evidence shape

Each completed action stores the target, method, status, UTC timestamp, allowlisted headers, findings, conclusion, coverage/limit notes, and SHA-256. A completed retest additionally stores its comparison. The report includes every action and ordered audit entries with verification flags. Inspect `conclusion`: redirects, errors, and non-2xx responses do not establish that the header configuration is complete.

## Planning API (day 2)

Request to `/assessments/{id}/plans`:

```json
{
  "goal": "Review security headers on the authorized demo targets",
  "request_id": "39f23c5f-2145-46ec-a9fb-fc8c9312aba8"
}
```

`goal` is required, 1–1000 characters. `request_id` is an optional UUID; the server creates one if omitted. Provide a stable UUID when retrying after a lost response. New successful plans return 201; an identical replay returns 200 and the same saved plan. A reused ID with a different goal, assessment, or provider returns 409. Replaying a failed or denied request returns the recorded failure; use a new ID to attempt planning again.

Responses contain `id`, `assessment_id`, `goal`, `provider`, `model`, `status`, `summary`, `error_code`, creation/finish timestamps, `action_ids`, linked `proposals`, and `sha256`. Plan status is `running`, `completed`, `denied`, or `failed`. A completed plan means proposals were generated, not that checks were executed. Generated actions carry a `plan_id` and begin `pending`.

Planning adds 502 for invalid/duplicate provider output, 503 for provider failures or interrupted plans, 504 for the provider deadline, and 429 for planner concurrency limits. Policy escapes return 403; stale proposals return 409. Error details have `{ "message": "...", "plan_id": "..." }`. Raw provider output and exceptions are never included.

Assessment responses now include `plans`. JSON reports use `schema_version: 2`, add all plan records, and include `integrity.plan_hashes_valid`. This flag checks plan metadata and linked proposal fields against their completion audit events. A report's local hashes still do not prevent whole-database rewriting by its owner.

## Day-three provider mode and errors

`GET /planner` returns `provider`, `model`, `mode`, `live_ai`, `allowed_tools` and `requires_approval`.
Offline mode is `rule_based` / `live_ai: false`; the configured OpenAI-compatible adapter is `llm` / `live_ai: true`.
These fields identify adapter configuration, not provider reachability or successful generation. Keys and base URLs are not exposed.

The deadline is now configurable, default 30 seconds. Set an API client timeout slightly above your chosen planner deadline.
New trusted failure codes are `provider_auth` (503), `provider_rate_limited` (429), `provider_response` (502),
`provider_refused` (502), and `provider_input` (422). Existing `provider_failed` and `timeout` remain 503 and 504.
A goal containing a known configured credential returns 422 before any plan is stored. Schema and scope denials remain unchanged.
The API never accepts provider configuration, credentials, a model-selected endpoint or an approval instruction in planning requests.
See [provider setup](PROVIDER_SETUP.md).

## Optional evidence context (October 17)

Add `"include_evidence": true` to the planning request to include compact observations
from completed checks. The default is false; strings/numbers are rejected. Reusing the UUID
with a different evidence option returns 409. Identical retries replay the original snapshot.

Opt-in plans contain `evidence_context` with `schema_version: 1`, `observations` and
`omitted_count`. Up to three latest-per-URL results fit within a 4096-byte budget.
Each result has `evidence_id` (action UUID), original `sha256`, `target`, `status_code`,
`conclusion`, `csp_present`, `nosniff_valid`, and `referrer_policy_present`.
Non-2xx results have an inconclusive conclusion and null booleans. The observations
describe header presence/exact nosniff matching, not exploitability.

Raw header values and stored free-text findings are excluded. The snapshot is persisted and
covered by completed-plan integrity. Broken report/evidence integrity returns 409 before
contacting the provider. No new approval or execution behavior is introduced. Offline baseline
rules are unchanged. See [DAY_5.md](DAY_5.md) for limits, compatibility and validation.

## Continue an assessment (October 19)

After resolving the latest plan's actions, send:

```json
{"request_id": "25f5d43d-a556-40f8-bc97-58dcb5447ea1"}
```

to `POST /assessments/{id}/continue`. The UUID is optional but should be stable on retry.
The inherited goal/provider and bounded evidence context are selected by the backend.
No other request fields are accepted. A successful new continuation returns 201; replay returns
200 with the original saved predecessor/context. Normal planning error codes still apply.

Each sequence has at most four planning attempts including its initial plan. Pending, approved or
running actions block continuation. Failed/denied plans, an empty final plan, a provider change,
and exhausted budgets require review instead of another continuation; invalid progression returns
409 before any provider request. New proposals remain pending. No automatic checks are run.

Assessment details and reports now include `planning_progress` with status, steps used, maximum
steps, latest plan ID and a `can_continue` flag. Continued plans include `continuation_of`.
The cap is per sequence: explicitly generating a new initial plan starts a new one.
See [Day 6 notes](DAY_6.md) for states, replay, transaction guards and limitations.
