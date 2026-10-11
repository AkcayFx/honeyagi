# Local API

Base: `http://127.0.0.1:8000/api/v1`. All API endpoints require `Authorization: Bearer <terminal token>`. Mutations require `Content-Type: application/json`, including `{}` for decisions without a note. The local dashboard handles these headers automatically.

| Method | Path | Result |
| --- | --- | --- |
| GET | `/assessments` | List assessments |
| POST | `/assessments` | Create immutable scope |
| GET | `/assessments/{id}` | Assessment and action queue |
| GET | `/planner` | Provider identity and whether live AI is available |
| POST | `/assessments/{id}/plans` | Generate a validated plan with pending proposals |
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
                  trust_env=False, timeout=10) as client:
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
