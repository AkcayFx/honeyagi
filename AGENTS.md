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

Read `docs/ROADMAP.md` and `docs/DAY_2.md`. The deterministic fake planner, typed provider interface, provenance and output-denial tests are implemented. Day 3 adds the OpenAI-compatible adapter in `app/providers.py`. Its output creates ordinary pending proposals through the same validation path. Read `docs/DAY_3.md` and `docs/PROVIDER_SETUP.md`. Next verify a real model call with locally configured credentials; mock transport success does not complete live verification. Do not change policy or enable new scanning tools just to make a model response succeed. Keep the offline provider labelled rule-based, and distinguish configured LLM mode from successful live verification. October 14 adds `python -m app.verify_planner --interactive`: hidden key entry, a disposable database, rejecting tool guard and redacted result files. Read `docs/DAY_4.md`. October 17 adds optional bounded observations in `app/evidence.py`; read `docs/DAY_5.md`. Keep raw target text out of model context, preserve saved context on replay, and retain old plan hashes during additive migration. October 19 adds operator-triggered feedback with four-attempt sequences, unchanged approval rules, replay provenance and dashboard progress. Read `docs/DAY_6.md`; keep continuation explicit and enforce limits in the insertion transaction. Development Day 4 remains incomplete until a real model request succeeds. Do not claim a live model ran until it is demonstrated.

If asked to make commits, make small truthful commits after functional changes. Do not fabricate progress, backdate commits, or push to an unknown repository.
