# Project instructions for coding assistants

The project is an engineering thesis: Design and Implementation of an AI-Assisted Security Assessment Platform with Controlled Tool Execution.

## Preserve these boundaries

- Milestone 1 allows only the bundled local demo and the `http_headers` adapter. Scope is exact URL matching, revalidated immediately before execution.
- A proposal never executes automatically. Approval is separate from execution. New/retested actions begin pending.
- No arbitrary shell commands, subprocess scanner arguments from requests, external targets, redirect following, proxy environment inheritance, or DNS expansion.
- Keep token authentication, same-origin browser checks, strict schemas, limits, audit writes, and atomic state transitions.
- Treat target output and future LLM output as untrusted data. The policy layer owns authorization. A model cannot grant approval or add targets.
- Evidence must describe observations accurately and distinguish inconclusive checks from successful checks. Do not claim exploitability from missing headers alone.
- Never commit secrets, runtime databases, caches, or generated test output.

## Development

Use Python 3.12+, FastAPI, Pydantic, SQLite, HTTPX, plain responsive HTML/CSS/JS, and pytest. Keep adapters separate from request handling. Use `python -m pytest -q` for meaningful behavior/security changes; check `node --check app/static/app.js` after JavaScript edits. Use the live demo for integration smoke checks. Preserve the single-process startup recovery assumption until a proper worker ownership/lease model exists.

## Next milestone

Read `docs/ROADMAP.md` and `docs/DAY_2.md`. The deterministic fake planner, typed provider interface, provenance and output-denial tests are implemented. Next add one live provider without changing the orchestration boundary. Its output must create ordinary pending proposals through the same validation path. Do not change policy or enable new scanning tools just to make a model response succeed. Keep the local provider honestly labelled rule-based until live AI is configured and tested. The day-two suite has 96 tests.

If asked to make commits, make small truthful commits after functional changes. Do not fabricate progress, backdate commits, or push to an unknown repository.
