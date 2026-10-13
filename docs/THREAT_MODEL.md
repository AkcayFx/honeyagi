# Threat model — controlled execution and planning

## Assets and trust boundaries

The operator's token, approved assessment scope, action state, evidence, audit records, and local network boundary are the assets. Browser input and target response headers are untrusted. The API validates requests; the policy constrains tools and targets; the adapter performs one bounded request; SQLite persists state and evidence.

The local operator is trusted to possess authorization for the bundled demo. The database and host OS are trusted. There is one operator identity (`local_operator`) and one process. The access token is a local access control, not multi-user authentication or an approval signature.

## Threats and controls

| Threat | Implemented control | Verification |
| --- | --- | --- |
| Scope escape / SSRF | Literal loopback origin and three exact paths; exact per-assessment URL scope; no DNS, credentials, queries or encodings | URL attack cases and scope-denial tests |
| Redirect escape | Redirect following disabled; non-2xx response inconclusive | Redirect test confirms one request |
| Ambient proxy forwarding | `trust_env=False` on adapter client | Explicit adapter configuration; live loopback check |
| Unapproved execution | `pending → approved → running` atomic transitions | Execute-before-approval and rejection tests |
| Duplicate execution | Compare-and-swap in a write transaction | Replay test and concurrent claim test |
| Tool/parameter injection | Literal allowlisted tool, forbidden extra fields, no shell executor | Unknown-tool and parameter tests |
| Browser cross-origin invocation | Bearer token, trusted Host list, Origin allowlist, no CORS, JSON mutation requests | Boundary tests |
| Stored XSS from headers or names | Dynamic UI values inserted with `textContent`, restrictive CSP | Implementation review and browser workflow |
| Resource pressure | Request body cap, field limits, two running checks, total timeout, accepted-header cap, no response body retained | Size, concurrency, and timeout tests |
| Sensitive header disclosure | Only three security headers retained; no cookies, auth, or body evidence | Redaction tests |
| Partial or lost execution | Running actions fail on restart; explicit new retest required | Restart recovery test |
| Simple evidence or log mutation | SHA-256 evidence, completion-event binding, hash-linked audit | Tamper detection tests |

## Limits and decisions

This is a lab foundation, not a production pentesting system. The processes are not OS/container sandboxes; the current adapter has no shell or external target capability. A host administrator can change code, scope, stored data, tokens, and hashes. Entire-log deletion or rewriting is not cryptographically prevented. No external anchoring or signed approvals exist.

The header byte limit is enforced after HTTPX has parsed headers; it is not a raw socket memory cap. The services rely on the local OS for process isolation. Database growth, slow API uploads, queued HTTP requests, and malicious activity by an authorized operator are not fully bounded. Public hosting, multi-user use, or remote targets require a new threat model and appropriate controls first.

The launcher checks whether the ports are free before starting, but this is not an authenticated claim of target process identity and does not eliminate a local port-race attack. Assessment scope is immutable through the API. Retests do not switch endpoints; use a new scoped proposal for a comparison target.

For future AI: target output is evidence, never instruction. A planner must return structured proposed actions, which are schema-checked and policy-checked before insertion. The model must never receive the local operator token or possess an approval/execute capability. Scanner workers require process isolation, resource ceilings, egress policy, and safe adapter arguments.

## Day-two planner boundary

The planner interface receives only the bounded operator goal, immutable exact target URLs, names of allowed tools, and existing `(tool, target)` pairs. It receives no operator token, database object, HTTP executor, response headers, or raw evidence. The default provider is deterministic and makes no external requests. The optional Day 3 adapter sends only this selected context to an explicitly configured provider endpoint. Provider code is trusted application code, not a sandbox; an adapter can still import host resources. The interface constrains data/capabilities supplied by orchestration and is not an OS security boundary.

Provider responses are untrusted JSON text, limited to 16 KiB, one bounded summary, and at most eight typed header-check proposals. Duplicate JSON keys, unknown tools, extra fields (including approval/execution instructions), duplicate checks, and scope escapes are denied. All actions in a plan must validate before any are inserted. Scope and existing checks are rechecked inside the insertion transaction, so concurrent manual proposals cannot silently create duplicate planned checks.

Each accepted request has a persisted UUID and fingerprint. Same-input retries replay the saved plan; conflicting reuse is rejected. Planning is limited to one in-flight request per assessment and two globally, with a configurable total provider deadline (default 30 seconds, at most 120). Startup recovery marks interrupted plans failed. This async deadline assumes cooperative provider code; it cannot interrupt a provider blocking the event loop with CPU work.

Plan goals, trusted provider/model identifiers, and linked proposals are stored separately from tool evidence. A plan SHA-256 is bound to its completion audit event. Reports verify its metadata and linked proposal fields. Denials/failures record generic reason codes; raw provider payloads and error messages are not persisted. Raw target-output prompt injection is currently excluded by not passing target text to the planner. Future evidence-aware live providers need explicit injection evaluation before adding that input channel.

## Day-three external provider boundary

The provider API key is a separate asset from the dashboard access token. Live mode is opt-in and must have explicit model/endpoint configuration.
The trusted operator chooses the provider endpoint through environment variables; model output and browser API requests cannot change it.
The remote provider receives the bounded goal, scope, allowed tools and existing check pairs. Raw evidence is still excluded.
This is an intentional external data boundary in live mode; the provider's own retention and security are not controlled by HoneyAGI.

HTTPS is required remotely; only exact loopback hosts may use HTTP or omit a key. Credentials, queries, fragments and ambiguous encoded base URLs are rejected.
The key is sent in an Authorization header only. Settings repr excludes both keys and dashboard tokens.
Known configured credentials pasted into goals are rejected before persistence; this is not general secret detection.
Response framing that echoes known credentials is rejected. Raw error bodies and exceptions are not recorded.

Outbound requests have a 16 KiB body limit, a configurable completion budget, disabled redirects/proxy inheritance and no automatic retries.
The response envelope is capped at 64 KiB; compressed bodies are rejected before consumption, and accepted headers are capped after parsing.
Response streams and clients close on deadlines, failures and cancellation. Parsed-header limits still are not raw socket memory limits.
Only one complete assistant text choice is accepted; refusal, truncation, returned tool calls, malformed envelopes and invalid plans create no actions.
The existing policy and all-or-nothing transactional insertion own authorization even when upstream strict structured output is enabled.

No successful live call is claimed in Day 3 validation. Mocked transport tests exercise these boundaries; Day 4 adds verification with real configured credentials.
Container isolation, broader scanner tools and evidence-aware adaptive planning remain separate future work.
