# October 14 — planner verification tooling

This session advances development Day 4. Its live-model acceptance check remains **incomplete**: the environment still selects the offline provider and has no configured model or planner API key.

## Delivered behavior

- `python -m app.verify_planner` checks the configured planner and writes a unique JSON result under `data/planner-verifications/`.
- `--interactive` reads a model ID and, for remote providers, a hidden key in a local terminal. The key stays in process memory; it is not a command-line argument or written to environment/configuration files. Interactive input is rejected when it cannot be hidden.
- The command uses a disposable database and a new temporary access token. It does not modify the operator's database, need a running dashboard/demo, approve actions, or run a tool.
- It tests configured provider identity, successful nonempty pending proposals, denied unauthenticated approval, denied unapproved execution, idempotent request replay and report hash verification.
- The tool adapter is replaced with a rejecting guard. Even an execution-boundary regression cannot cause this verification command to contact an assessment target.
- Results distinguish `not_configured`, `configuration_error`, `failed`, `simulated`, `interrupted` and `passed`. Injected test providers cannot set `live_verified: true`.
- Each result records UTC timestamps, elapsed time, configured provider/model, check flags, proposal count, plan hash and trusted failure codes. It excludes keys, raw provider text, model-written rationales and base URLs.
- A related credential fix rejects secrets in **decoded** summaries/rationales before storage. Unicode JSON escaping no longer bypasses the raw-response credential check.

## Validation

- **200 tests pass**: 172 existing tests plus 28 verification/credential cases.
- New checks cover preserved operator state, no token announcement, explicit failure/skip results, hidden-input behavior, non-overwriting JSON result files, approval-boundary regressions and escaped credential echoes.
- A real loopback HTTP contract fixture exercises the adapter and verification flow. It serves canned output and remains labelled simulated; it is not live-model evidence.
- The real API/demo smoke still passes with mocked model transport: two pending proposals, denied unapproved execution, approved 3/0 observations and verified hashes.
- Running the actual command with today's configuration returns exit 2, `not_configured`, `live_verified: false`, and zero tool calls. It does not call a model.
- No successful real-model call, scanner expansion or adaptive evidence loop is claimed.

## Finish the live acceptance check

From the installed repository, run:

```powershell
.venv\Scripts\python.exe -m app.verify_planner --interactive
```

Enter a supported model ID and the provider key privately in your local terminal. Existing provider/base-URL/format environment settings still apply. Read [PROVIDER_SETUP.md](PROVIDER_SETUP.md) first if using a compatible local server or a different endpoint.

A configured-endpoint pass verifies this limited planning workflow against the endpoint the operator selected. It does not establish the model's assessment quality, identify what model a third-party server actually runs, or prove successful tool execution. Do not mark development Day 4 complete from canned or simulated endpoint output.
