# Day 3 — configurable LLM planner (2026-10-13)

HoneyAGI v0.3 adds an OpenAI-compatible planner behind the existing typed interface. Development Day 3 was completed on October 13, 2026, Europe/Warsaw.

## Delivered

- Explicit environment-based provider, model, base URL, credentials, response format, deadline and completion budget.
- Offline mode remains the default. Live mode requires valid configuration and never silently falls back.
- A bounded, non-streaming Chat Completions adapter with strict JSON-schema generation or explicitly selected JSON object mode.
- Local validation remains authoritative: no approval/execution fields, unknown tools, scope changes, duplicate checks or partial proposal insertion.
- Authentication, rate limit, network, timeout, refusal, truncation, malformed envelope and size-limit failures have honest error codes.
- Provider keys stay in request headers; dashboard tokens and raw tool evidence stay out of model context. Known credentials in goals are rejected before persistence.
- Dashboard planner labels and help text reflect the configured mode/model. API `live_ai: true` identifies the configured LLM adapter, not proof of a successful live call.
- Setup instructions and updated threat-model/API documentation.

## Verification

- **172 tests pass**: the existing 96 cases plus 76 provider/configuration cases.
- JavaScript syntax check passes.
- Real loopback API and demo smoke workflow passes using the new adapter with a **mocked provider transport**: two pending proposals, execute-before-approval denial, explicit approval/execution, three observations on `/vulnerable`, zero on `/hardened`, and valid audit/evidence/plan hashes.
- Response streams close on oversized output, rejected compression and deadline cancellation.
- No planner API key was configured, so no successful live-model call is claimed. No external assessment target was contacted.
- Windows test-directory permissions use the same process-local adjustment as prior sessions. Normal checkouts use `python -m pytest -q`.

## Next task

Day 4: configure a provider locally and demonstrate one real model plan. The mock/error checks are in place; live verification remains pending. See [PROVIDER_SETUP.md](PROVIDER_SETUP.md).

## Repository

`AkcayFx/honeyagi`. The preceding Day 2 and checklist commits were pushed on October 12. Today's implementation and documentation are committed together after verification; use the Git history for the final commit ID.
