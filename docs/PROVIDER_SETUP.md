# Configure the Day 3 planner

HoneyAGI v0.3 has two explicit modes:

- `fake`: deterministic offline header baselines; no model requests or API key.
- `openai_compatible`: the configured model proposes actions through a Chat Completions endpoint. All output still passes the same schema, scope and transactional checks. Actions start pending.

Selecting the live adapter means it is configured, not that a successful live request has been demonstrated. The Day 3 regression suite uses mocked provider responses. Live-model verification is the next task; no live provider key was configured during this development session.

## OpenAI-compatible remote endpoint

In PowerShell, select a model that your provider supports, then enter its key without putting it into a command or Git:

```powershell
$env:SAP_PLANNER_PROVIDER = "openai_compatible"
$env:SAP_PLANNER_MODEL = "YOUR_MODEL_ID"
$env:SAP_PLANNER_BASE_URL = "https://api.openai.com/v1"
$env:SAP_PLANNER_API_KEY = [System.Net.NetworkCredential]::new("", (Read-Host "Planner API key" -AsSecureString)).Password
.venv\Scripts\python.exe run.py
```

Replace `YOUR_MODEL_ID` with a model available to your account that supports Chat Completions and the selected response format. Keys are read only from `SAP_PLANNER_API_KEY`; an unrelated `OPENAI_API_KEY` does not silently enable the adapter. Keep the terminal private.

Connect to the dashboard, create a scoped assessment, and click **Generate plan**. The badge shows the configured model. The goal and scoped tool/check list are sent to your configured provider; raw evidence and the dashboard token are excluded. The provider key is sent only as its Authorization header. Treat the goal as information you are willing to send to that provider.

Afterward, remove the credential from this terminal if you no longer need it:

```powershell
Remove-Item Env:SAP_PLANNER_API_KEY
```

## Local compatible server

A server on an exact loopback host may run without a key:

```powershell
$env:SAP_PLANNER_PROVIDER = "openai_compatible"
$env:SAP_PLANNER_MODEL = "YOUR_LOCAL_MODEL_ID"
$env:SAP_PLANNER_BASE_URL = "http://127.0.0.1:1234/v1"
Remove-Item Env:SAP_PLANNER_API_KEY -ErrorAction SilentlyContinue
.venv\Scripts\python.exe run.py
```

The server must already be running and support the request contract below. If it supports JSON object mode but not strict JSON schemas, explicitly set:

```powershell
$env:SAP_PLANNER_RESPONSE_FORMAT = "json_object"
```

This changes the upstream generation format only. Local schema, byte-limit, scope and approval checks still apply. The adapter never automatically downgrades the format, retries requests, or substitutes the offline planner.

## Configuration

| Variable | Default | Rule |
| --- | --- | --- |
| `SAP_PLANNER_PROVIDER` | `fake` | `fake` or `openai_compatible` |
| `SAP_PLANNER_MODEL` | Empty | Explicit model ID required in live mode |
| `SAP_PLANNER_BASE_URL` | `https://api.openai.com/v1` | Appends `/chat/completions`; HTTPS remotely, HTTP permitted only on exact `127.0.0.1`, `localhost`, or `::1` |
| `SAP_PLANNER_API_KEY` | Empty | Required remotely; optional on loopback; never put in the URL |
| `SAP_PLANNER_RESPONSE_FORMAT` | `json_schema` | Explicit `json_schema` or `json_object` |
| `SAP_PLANNER_TIMEOUT` | `30` seconds | Greater than zero, at most 120; total cooperative deadline |
| `SAP_PLANNER_MAX_TOKENS` | `2048` | 128–4096; sent as `max_completion_tokens` |

Invalid provider names, missing live configuration and unsafe base URLs stop application startup with a generic configuration error. There is no implicit fake-provider fallback. The model cannot choose the endpoint or credentials. Planner endpoint configuration does not expand assessment target scope.

The `.env.example` file documents names only. The launcher does **not** automatically load dotenv files: set environment variables in your terminal or process manager.

## Request contract and failure behavior

One non-streaming `POST /chat/completions` sends a system instruction, a JSON context in a user message, the explicit model, the selected response format, `max_completion_tokens`, `n: 1`, `stream: false` and `store: false`. No function/tool-call interfaces are supplied. Compatible providers must accept these fields; unsupported fields cause an honest failure. `store: false` is a request setting, not a promise about another provider's retention policy.

The request body is limited to 16 KiB. The returned completion envelope is limited to 64 KiB and parsed with duplicate-key rejection; its content remains subject to the existing 16 KiB plan limit. Only a single assistant text completion with `finish_reason: stop` is accepted. Refusals, truncation, returned tool calls, invalid framing and compressed responses produce no proposals. TLS verification remains enabled, redirects and proxy environment inheritance are disabled. Fresh HTTP clients close on completion, denial, timeout or cancellation.

| Failure | API result |
| --- | --- |
| 401/403 upstream authentication | 503 with a generic credential-configuration message |
| 429 upstream rate limit | 429 with a generic retry-later message |
| Network errors or other unsuccessful upstream status | 503; no automatic retry |
| Deadline or HTTP timeout | 504 |
| Refusal, incomplete/invalid completion envelope | 502 |
| Invalid plan JSON/schema/duplicates | Existing 502 denial |
| Out-of-scope proposal | Existing 403 denial |
| Goal containing configured credentials | 422 before persistence or any provider request |

Failures are stored using trusted reason codes, without raw provider errors or response bodies. Known configured credentials accidentally pasted into a goal are rejected before a plan record is created. Never put other secrets in goals or manual rationales; this check is not a general secret detector.

Provider code and the host remain trusted application code. This is not a container sandbox. Operator approval and explicit execution are still separate requests, and only the existing bundled header-check demo is assessable.

## Next live verification

1. Configure your chosen provider/model locally and start the lab.
2. Generate one real plan for a fresh assessment and inspect its provenance and pending proposals.
3. Confirm no check runs until you approve and execute it.
4. Record the provider/model, observed result, timing, and any denial/failure without recording the key.
5. Mark Day 4 complete only after a real model request succeeds; mocks do not satisfy that acceptance check.

Official contract references: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
