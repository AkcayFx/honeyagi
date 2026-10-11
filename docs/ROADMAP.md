# Implementation roadmap

For the day-by-day implementation tasks, acceptance checks and suggested commits, see [DAILY_TASKS.md](DAILY_TASKS.md). The next task is day 3: the first live LLM provider. The daily checklist targets an evaluated MVP first, followed by the broader capability backlog.

## Milestone 1 — delivered

Controlled execution, strict scope, operator decisions, real header adapter, local demo, dashboard, SQLite storage, evidence, retesting, reports, and tests.

## Milestone 2 — AI proposes, operator decides

Day 2 completes the typed provider interface, deterministic fake provider, pending-proposal generation, dashboard planning workflow, provenance/report integration, and adversarial validation tests. No live LLM adapter is implemented yet.

1. Define `Planner` and `PlanRequest`/`PlanResponse` schemas. A plan consists of rationale plus proposed allowlisted actions; it has no approval or execution fields.
2. Build a deterministic fake provider for repeatable tests and an explicit “Generate plan” dashboard action.
3. Route generated actions through the existing schema and policy validation. Store planner provenance and model identifiers separately from tool evidence.
4. Test malformed JSON, hallucinated tools, out-of-scope targets, extra arguments, and prompt injections from captured target text. Invalid model output should produce an explainable denial, never a scope expansion.
5. Add one live provider behind environment configuration, with bounded requests and no operator token sent to the provider. Test offline behavior and honest failure handling.

Acceptance: both fake and live planners create pending proposals only. Existing policy and approval tests still pass. The provider is replaceable without changing authorization decisions.

## Milestone 3 — isolated scanner workers

Move execution behind a queue with worker leases and interruption recovery. Add container isolation and explicit egress policy. Then add one tightly parameterized scanner adapter at a time, with resource limits and output parsers. Resolve target identity and DNS pinning before allowing non-loopback targets. Build a separate authorized lab for broader evaluations.

## Milestone 4 — thesis evaluation

Compare manual planning, deterministic planning, and LLM planning on the same fixed lab cases. Measure valid-action rate, denied-action rate, approval burden, successful checks, evidence correctness, reproducibility, execution time, and retest accuracy. Report false conclusions and failure cases. Distinguish scanner coverage from LLM reasoning performance.

## Meaningful commits

Day-two commit: `feat: add validated assessment planning and provenance`. Suggested next commits: `feat: integrate one live planner provider`, `test: evaluate live planner failures and prompt injection`, `docs: add lab evaluation protocol`. Commit after a real change and its relevant checks. The repository is `AkcayFx/honeyagi`. Day-two changes are prepared locally; push only when requested.
