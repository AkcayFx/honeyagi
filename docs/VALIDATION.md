# Validation record — 2026-10-11

Environment: Windows, Python 3.12, FastAPI 0.135.2, Pydantic 2.12.5, HTTPX 0.28.1, Uvicorn 0.42.0, pytest 9.0.2.

- 56 pytest cases passed. Tests run against temporary SQLite databases and mocked HTTP adapters.
- `node --check app/static/app.js` passed.
- Local launcher started the actual demo and API on loopback ports 8001 and 8000.
- Browser workflow verified: token connection, assessment creation, proposal, approval, execution, completed status, three header observations on `/vulnerable`, and visible audit verification.
- A separate live API workflow verified `/vulnerable` (three observations), `/hardened` (zero), `/redirect` (inconclusive), execute-before-approval denial, a newly approved retest, and report integrity checks.
- No live AI provider is implemented or tested in this milestone. No external assessment target was contacted.

The execution environment restricted pytest-created directories with owner-only permissions. The validation run used a workspace test directory and a process-local mkdir permission adjustment; application code and tests were unchanged. In a normal local checkout, run `python -m pytest -q`.

## Day 3 — 2026-10-13

- 172 pytest cases pass, including 76 additional live-adapter/configuration regression cases. No warnings remain in this run.
- `node --check app/static/app.js` and `git diff --check` pass.
- Real loopback API/demo HTTP smoke uses the OpenAI-compatible adapter with mocked model transport: two pending checks, denied unapproved execution, explicit approval/execution, expected 3/0 observations and verified report hashes.
- Oversized/compressed responses and read-timeout cancellation close response streams.
- No live provider credential was configured. Mock success does not establish successful real-model planning.
- The smoke database stays outside tracked source; temporary services shut down after validation.
- See [DAY_3.md](DAY_3.md) and [PROVIDER_SETUP.md](PROVIDER_SETUP.md).
