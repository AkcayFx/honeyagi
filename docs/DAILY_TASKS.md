# HoneyAGI daily development checklist

**Thesis:** Design and Implementation of an AI-Assisted Security Assessment Platform with Controlled Tool Execution.

**Goal:** build a complete AI security assessment platform with real planning, several security tools, isolated execution, evidence, retesting, and reports. Build the controls and evaluation needed to demonstrate improvements over comparable systems such as Sentrix.

**Repository:** `AkcayFx/honeyagi`.

Day numbers describe development sessions, not deadlines. Aim for one useful increment per session and 1–3 meaningful commits when the work supports them. A difficult task can span multiple days. Move to the next task when its acceptance check passes. The first 30 sessions target a working, evaluated MVP; the advanced backlog expands its capabilities afterward.

## Current progress

- [x] **Day 1:** assessment dashboard, exact lab scope, approval/execution workflow, header checker, evidence, audit, retests and JSON reports. Pushed to GitHub.
- [x] **Day 2:** typed planner interface, deterministic offline provider, planning UI, provenance, replay protection and adversarial validation. **96 tests pass.** Commit `0a27b15422cc0f86eeb5120e201532adade11217`; pushed October 12, 2026.
- [x] **Day 3 (October 13, 2026):** configurable OpenAI-compatible adapter, explicit model/credentials, bounded requests, honest failures, mode-aware UI and 76 additional tests. **172 tests pass.** Provider responses were mocked; the local demo workflow used real HTTP. See [DAY_3.md](DAY_3.md).
- [ ] **Day 4 live acceptance — still pending.** October 14 delivers the repeatable verification command, hidden key input, redacted results, decoded-credential protection and 28 additional cases: **200 tests pass**. The actual command correctly reports offline/unconfigured mode; no real model/key was available. See [DAY_4.md](DAY_4.md).
- **Next action:** run `python -m app.verify_planner --interactive` locally with a real provider/model. Proceed to bounded evidence summaries after live verification passes.

## Days 3–7: real AI and the assessment loop

| Day | Main task | Done when | Suggested commit |
| --- | --- | --- | --- |
| 3 | Implement an OpenAI-compatible planner adapter and explicit local provider/model configuration. | Mocked successful responses create validated pending proposals through the existing service; no token or database access is passed to the model. The fake provider remains available. | `feat: add configurable live LLM planner` |
| 4 | Verify live planning and handle provider failures. | With a locally configured API key, one real lab plan succeeds. Missing keys, authentication failures, rate limits, malformed output and timeouts produce honest errors. Secrets are absent from logs and Git. | `test: verify live planner success and failure paths` |
| 5 | Add compact evidence summaries for the model. | The model receives only selected observations with evidence IDs; credentials, cookies and raw target text are excluded. Instructions embedded in evidence cannot change policy. | `feat: add bounded evidence context for planning` |
| 6 | Implement the assessment feedback loop. | After an approved check finishes, the model can propose a useful next check or finish. New actions remain pending. Step/request limits stop endless loops and duplicate checks. | `feat: add assessment reasoning loop` |
| 7 | Generate a final assessment summary with validated citations. | Each factual finding cites existing evidence. Unsupported evidence IDs and invented results are rejected. One live goal-to-report lab workflow is demonstrated. | `feat: generate reports grounded in evidence` |

**Milestone:** a real model plans, receives approved check results and produces a traceable report. A live API key is needed for the live verification tasks; mocked tests alone do not mark those tasks complete.

## Days 8–14: isolated execution and real scanner support

| Day | Main task | Done when | Suggested commit |
| --- | --- | --- | --- |
| 8 | Build a Docker Compose lab and a worker boundary. | The demo target and worker start reproducibly on an isolated lab network. The API does not receive a Docker socket or arbitrary shell capability. Document how the scoped lab target is identified. | `feat: add isolated assessment lab and worker` |
| 9 | Add durable jobs, atomic claims and worker leases. | A job has one owner; retries cannot execute it twice. Worker loss is distinguishable from successful completion. Replace the current single-process recovery assumption before enabling multiple processes. | `feat: add durable execution jobs and leases` |
| 10 | Enforce worker authentication and resource limits. | The worker accepts only authorized job envelopes. Time, process, output and concurrency limits are tested; the lab worker cannot reach outside its allowed network. | `feat: enforce worker execution boundaries` |
| 11 | Add a tightly parameterized Nmap adapter. | A non-root TCP connect/service check runs against an explicitly authorized lab target. The backend selects fixed command structure; model/request input cannot supply shell commands or arbitrary flags. | `feat: add scoped Nmap lab adapter` |
| 12 | Parse and store scanner evidence. | Open ports and observed services become structured observations linked to the exact job. Malformed, oversized and hostile scanner output fail safely. Service detection is not presented as confirmed exploitability. | `feat: parse Nmap evidence into observations` |
| 13 | Move the header checker behind the worker and expose typed tool metadata to the planner. | The model can choose between the two registered tools. Approval, target scope, revalidation, limits and evidence rules apply to both adapters. | `feat: unify planner tools behind worker execution` |
| 14 | Demonstrate a complete assessment using both adapters. | A real model proposes lab discovery and web checks, receives their results and reports with evidence citations. Unapproved and out-of-scope execution attempts are denied. | `test: cover the complete AI assessment workflow` |

**Milestone:** useful real tool execution through an isolated, controlled worker. Non-loopback lab support needs an explicit scope-policy change and tests; do not silently relax the current allowlist.

## Days 15–21: capabilities, findings and operator controls

| Day | Main task | Done when | Suggested commit |
| --- | --- | --- | --- |
| 15 | Add a second provider, such as Anthropic, behind the same interface. | Both providers produce the same internal proposal structure and obey identical validation. Provider selection is explicit; failures do not silently pretend a live model ran. | `feat: add a second LLM provider` |
| 16 | Manage context and token budgets. | Goals and authorization rules remain available when older results are summarized. Input/request limits are configurable and truncation is visible in provenance. | `feat: manage assessment context budgets` |
| 17 | Create a structured finding model. | Findings have stable IDs, affected targets, observations, confidence, severity rationale, remediation advice and valid evidence references. Speculation is distinguishable from observations. | `feat: add evidence-linked security findings` |
| 18 | Extend explicit retesting to findings and worker adapters. | The same scoped check can be repeated after a lab change. Reports distinguish still observed, no longer observed and inconclusive outcomes. Existing evidence remains intact. | `feat: add finding retests and comparisons` |
| 19 | Add live job/assessment progress to the dashboard. | The operator sees planning, review, queue, running and completion states without confusing generated proposals with completed checks. Connection loss does not duplicate work. | `feat: display live assessment progress` |
| 20 | Add cancellation and safe recovery. | The operator can stop their own job. Cancellation terminates its worker process; incomplete output is labelled. Restarting does not silently replay an uncertain execution. | `feat: add job cancellation and recovery` |
| 21 | Design approval modes around explicit operator authorization. | The operator may approve a bounded manifest of low-risk lab checks in advance. Other actions still require review. The model cannot alter scope, permissions, approval rules or execution budgets. | `feat: add bounded assessment approval policies` |

**Milestone:** an operator can manage a useful assessment agent, inspect its findings and reliably retest them.

## Days 22–30: broader checks, evaluation and a usable release

| Day | Main task | Done when | Suggested commit |
| --- | --- | --- | --- |
| 22 | Add a third scoped adapter: TLS/certificate inspection. | The lab includes known valid/invalid certificate cases. Observations identify certificate/verification issues without disabling protections for unrelated requests. The standard job and evidence controls apply. | `feat: add scoped TLS certificate checks` |
| 23 | Build a fixed evaluation lab with ground truth. | Five to ten documented cases specify expected observations, authorized targets and expected denials. Cases are reproducible without scanning third-party systems. | `test: add reproducible assessment benchmark cases` |
| 24 | Compare manual, rule-based and LLM planning. | The same cases and tools are used for each mode. Record result correctness, valid/denied proposals, completion time, operator approval burden and model usage. Preserve raw evaluation results. | `feat: add assessment evaluation harness` |
| 25 | Expand adversarial evaluation. | Goal injection, hostile tool output, scope escapes, secret disclosure, replay and forged evidence IDs are tested across the live-provider and worker boundaries. Report actual failures as well as successes. | `test: evaluate planner and worker attack boundaries` |
| 26 | Improve reliability and usage accounting. | Request/step budgets, transient failures, worker restarts and retries have defined behavior. Usage and timing are recorded; retries cannot duplicate a completed execution. | `fix: strengthen assessment reliability and budgets` |
| 27 | Export a readable assessment report. | Markdown output includes scope, methods, findings, evidence references, limitations, remediation and retest results. Exported claims match stored results. | `feat: export readable assessment reports` |
| 28 | Add continuous integration and verify setup documentation. | Tests run in GitHub Actions with limited permissions and no committed API keys. A fresh installation can start the lab and run the documented smoke workflow. | `ci: verify tests and reproducible lab setup` |
| 29 | Prepare the thesis/demo material from measured results. | Architecture, threat model, limitations, evaluation charts and a short demo explain what was implemented and what remains incomplete. All performance/safety claims point to measurements. | `docs: document architecture and evaluation results` |
| 30 | Stabilize and tag the first evaluated MVP. | Regression checks pass, important defects are resolved, setup/report/demo flows are verified, and release notes identify supported features and remaining limits. | `release: prepare the first evaluated HoneyAGI MVP` |

**Milestone:** an evaluated MVP with a real assessment loop, multiple providers, three scoped adapters, isolated execution and traceable reports. This is a foundation for approaching Sentrix's breadth; it is not a claim of superior detection capability or production readiness.

## Advanced backlog after the MVP

Move these into individual daily tasks after evaluating the MVP. Avoid adding features that weaken the existing execution boundary.

- [ ] **Assessment memory:** retrieve relevant earlier findings/evidence, with per-project access controls and verified source references.
- [ ] **Specialist agents:** planner, analyst and reporter roles with bounded delegation. Only the backend authorizes execution.
- [ ] **Expanded tool catalog:** add one authorized-lab adapter at a time, with typed parameters, parsers, limits and regression cases.
- [ ] **Safe web intelligence:** controlled retrieval for assessment context, with prompt-injection tests and explicit network policy.
- [ ] **Multi-project/user support:** authenticated identities, project ownership, roles and protected provider credentials.
- [ ] **Remediation workflows:** reviewable recommendations and authorized lab verification of fixes.
- [ ] **Shared capability benchmarks:** compare HoneyAGI with Sentrix on the same implemented checks and cases, rather than comparing tool counts alone.

## Daily commit and push routine

1. Pick the next incomplete task and state its acceptance check before coding.
2. Build a small working increment. Add tests when they verify a meaningful behavior or execution boundary.
3. Run the relevant checks and one lab smoke workflow when the execution path changes.
4. Inspect the diff. Commit only intended source/tests/docs; keep credentials and runtime data out of Git.
5. Create a truthful commit, then push the reviewed work to `AkcayFx/honeyagi` when requested.
6. Record what passed, what failed and the next task. Mark a task complete only after its acceptance check passes.

A feature, its meaningful regression tests and necessary documentation may be separate commits when each is coherent. Do not split unchanged work or create empty/backdated commits to fill the contribution graph. Larger tasks can produce honest intermediate commits such as a tested interface, parser or failure path.

## Progress entry template

```text
Development day:
Task:
Behavior delivered:
Acceptance check:
Tests/smoke checks run:
Local commit(s):
Pushed commit(s):
Open issues:
Next task:
```

Keep local and pushed status distinct. Day-two, checklist and Day-three commits were pushed on October 12–13. This checklist does not perform or schedule automatic pushes. Record new pushes in the Git history and session notes.
