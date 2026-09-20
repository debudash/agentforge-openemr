# Runnable API collection

`copilot-agent.postman_collection.json` — Postman v2.1, importable into Postman, Bruno,
Insomnia or `newman`. Ten requests covering the whole agent workflow end to end.

You should not need to read any source to run it.

## Setup

1. Start the agent service (see [copilot/README.md](../copilot/README.md)), or point at a
   deployed one.
2. Import the collection.
3. Set two collection variables:

| Variable | Value |
|---|---|
| `baseUrl` | `http://127.0.0.1:8600` for a local service |
| `sharedSecret` | `COPILOT_SHARED_SECRET` from `copilot/.env` |

4. Run the collection in order.

`sessionId` and `lastRunId` are already set and managed for you.

## Why a shared secret

The browser never talks to this service. OpenEMR proxies every call under the clinician's
session, and the agent has no public address, so this collection is the only way to drive
it directly.

Every request is signed:

```
X-Copilot-Signature: HMAC-SHA256(secret, "<unix ts>.<METHOD>.<path>.<raw body>")
```

A collection-level pre-request script does this for you — there is nothing to sign by hand.
An unsigned or stale request returns 401 by design, and the signature covers the path and
body, so a captured signature cannot be replayed against a different request.

## The requests

| # | Request | What it shows |
|---|---|---|
| 1 | Health | Liveness. Checks nothing else on purpose |
| 2 | Ready | Probes the model provider, LangSmith and OpenEMR; 503 if any is unreachable |
| 3 | Open session | Hands over a rounding list; briefs generate in the background |
| 4 | Status | Poll until every patient reads `ready` (10–30 s per brief on the free tier) |
| 5 | Select patient | Returns the brief; clears memory for every other patient |
| 6 | Ask a question | A grounded answer; every claim cites a record fetched this turn |
| 7 | Ask about another patient | `access_denied`, with no hint whether that patient exists |
| 8 | Rate the answer | Attaches a rating to that answer's LangSmith trace |
| 9 | Metrics | Counters, retries and latency percentiles since the service started |
| 10 | Close session | Drops every chart and conversation held for the session |

Request 3 carries a complete demo chart, so the workflow produces a real brief with real
citations without any other setup. The patient is synthetic.

## Things worth trying

- **Change the question in request 6** to something the chart cannot answer. The reply comes
  back `partial` or `unable_to_answer` with a reason, rather than a guess.
- **Ask for advice** — "should I increase her lisinopril?" — and watch it return the product
  boundary instead of a recommendation.
- **Ask something off topic.** You get a scope statement, and `iterations: 0`: the question is
  classified before any chart data or history is in play.
- **Break the signature** by changing `sharedSecret`, and every call returns 401.
- **Stop the agent and run request 2** against a service whose OpenEMR is unreachable; `/ready`
  returns 503 naming the dependency while `/health` stays 200.

## Health vs ready

Two endpoints, deliberately different:

- **`/health`** (alias `/healthz`) — is the process alive. Checks nothing else, so a dependency
  outage never causes an orchestrator to kill a service that is working.
- **`/ready`** (alias `/readyz`) — can it do its job right now. Probes the model provider
  endpoint, the LangSmith API and OpenEMR, and checks the provider allowlist and shared secret.
  Returns **503** when any of them fails, naming which.

`COPILOT_OPENEMR_URL` must be set for the OpenEMR probe. The agent never calls OpenEMR in
normal operation — data flows inward — so it cannot infer the address, and `/ready` reports the
dependency as unchecked rather than pretending it passed.
