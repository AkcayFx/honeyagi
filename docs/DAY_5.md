# October 17, 2026 — bounded evidence context

## Delivered behavior

The operator can check **Include compact observations from prior checks** before generating a plan.
The equivalent API field is `include_evidence: true`; it defaults to false and accepts only a JSON boolean.
The offline provider retains its deterministic baseline behavior. This feature supplies observations
to the configured live adapter; it does not add an automatic assessment loop.

A new opt-in request verifies the assessment report's audit chain, evidence hashes and completed-plan
hashes before contacting the provider. Invalid/missing/malformed evidence returns a generic 409 without
a provider request or a newly inserted plan.

The snapshot contains the latest completed check per scoped URL, ordered by completion events
rather than action creation time. It contains at most three observations and 4096 serialized bytes.
`omitted_count` reports earlier or budget-excluded completed results. Pending, failed, approved,
rejected and other-assessment actions never become observations.

Each observation contains:

- `evidence_id`: the originating action UUID, usable to locate the original evidence in the report;
- `sha256`: the original capture hash;
- the exact scoped `target`, HTTP `status_code`, and controlled `conclusion`;
- `csp_present`, `nosniff_valid`, and `referrer_policy_present` booleans.

For non-2xx responses, the conclusion is `inconclusive` and all three observations are null.
The booleans are derived from the allowlisted headers; stored finding prose is never copied.
Header presence does not prove policy quality, exploitability or application security.

Raw header values, finding descriptions, cookies, response bodies, errors, rationales, capture
timestamp strings and credentials are excluded. The provider receives immutable DTOs; HTTP request
and response limits, known-secret checks, schema validation and scope checks still apply.

## Provenance and compatibility

The exact sanitized snapshot is persisted with the plan, covered by its completed-plan hash,
and referenced by a context hash and included/omitted counts in `planning_started`.
Replaying a request returns its original snapshot, even after a retest finishes. Changing the
evidence option while reusing the request UUID returns 409.

The nullable database column is added without deleting records. Plans without evidence context
omit that field from serialization, retaining old fingerprints, completed-plan hashes and replays.
Opt-in planning fails closed if earlier evidence, audit or completed-plan integrity fails.
Hashes detect ordinary changes; a database owner can still rewrite records and hashes.

The system prompt explains the limited meaning of these observations and recommends citing
`evidence_id`. Factual citation validation is still a future reporting task; generated prose is
untrusted. New actions remain pending. Retests still use the explicit operator workflow.

## Validation

The new regression suite exercises immutable summaries, strict opt-in, redaction of hostile text
and configured secrets, scope/approval denial, completion ordering, retests, replay, visible budgets,
invalid evidence and additive migration. A smoke test starts the bundled demo on 127.0.0.1:8001 and
checks missing-header, configured-header and redirect cases over real HTTP before sending summaries
to a mocked provider.

Windows and Linux CI both passed **230 tests** (30 new cases), Python compilation, dashboard
JavaScript syntax and the offline verification CLI check. See the [feature validation run](https://github.com/AkcayFx/honeyagi/actions/runs/39045105456)
for source commit `c8b5752f4f94712a697b5d939f73dd1b473ceb3d`. The suite includes the real-loopback
smoke test above. Provider responses in these tests are simulated. **Development Day 4 real-model acceptance remains pending**; this implementation does
not demonstrate live reasoning or detection improvements over Sentrix.

## Next work

Run `python -m app.verify_planner --interactive` locally with a real provider/model/key.
Then evaluate an evidence-informed model request on the same fixed lab. The next implementation
task is a bounded, explicitly triggered assessment feedback loop with separate approval for every
new action.
