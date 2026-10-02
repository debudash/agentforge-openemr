# Runnable API collection

[`OpenEMR Clinical Co-Pilot - agent service/`](OpenEMR%20Clinical%20Co-Pilot%20-%20agent%20service/)
— the collection in Postman's local, one-file-per-request format, registered in
[`.postman/resources.yaml`](../.postman/resources.yaml) so Postman opens it from the repository.
Thirteen requests covering the whole agent workflow end to end.

You should not need to read any source to run it.

## Setup

1. Open the repository in Postman. The collection points at the live demo service, so nothing needs to be running
   locally; to drive a local service instead, start it first (see
   [copilot/README.md](../copilot/README.md)).
2. Open the Collection Runner.
3. Set one collection variable:

| Variable | Value |
|---|---|
| `sharedSecret` | see below |

`baseUrl` already points at the live demo, so there is nothing else to set: paste the secret and
run. Change it to `http://127.0.0.1:8600` if you would rather drive a local service.

**Where the secret comes from.** It is not in this repository, for the same reason the demo
logins are not: it is the credential that authorises every call to the agent. Request it with
the demo accounts — see the accounts table in the [root README](../README.md). If you are
running locally instead, it is your own `COPILOT_SHARED_SECRET` from `copilot/.env`, which you
generated when you set the service up.

4. Set **Delay 2000 ms**, and run.

`sessionId`, `lastRunId` and `statusTries` are set and managed for you.

The delay matters: a brief takes 10-30 s on the free tier, and request 4 re-runs itself
until every patient reads `ready`. Without a delay it spins through its forty attempts in a
second and gives up before the first brief lands. Running the requests one at a time works
too -- just press Send on request 4 until it reports `ready`.

## Why the live service is reachable at all

The agent normally has no public address. OpenEMR proxies every clinician request over
Railway's private network, and that is the PHI4 control: the browser never talks to the
agent or the model.

A public domain was added to the demo instance so this collection can be run against it
without a local stack. That is a deliberate trade, and it rests on two facts:

- **Every endpoint that touches a chart is signed.** `open`, `select`, `ask`, `feedback` and
  `metrics` all return **401** without the shared secret. Reaching the URL is not access.
- **The data is synthetic.** Every patient is Synthea-generated and contains no PHI.

`/health` and `/ready` stay unsigned, because Railway's own healthcheck and the deploy script
read them. They disclose the model name, the provider endpoint and the tracing project —
configuration, not credentials.

Handling real patient data would mean taking the domain off and returning to private-only,
where the collection runs against a local service and the deployed agent is exercised through
the OpenEMR UI. Nothing else about the design would change.

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
| 11 | Week 2: Read a lab report | The fixture two-page report through the vision model; every value carries a page and a quote, or the provider's 429 is reported as such |
| 12 | Week 2: Supervise | The supervisor graph with nothing unread: a brief plus the logged handoffs between agents |
| 13 | Week 2: Page with quote boxes | Page 1 of the report as an image, "Potassium" boxed where the text layer places it, an absent quote reported not drawn |

Requests 11–13 sit before Close so the session is still open; 11 needs a vision model with quota (free slugs often answer 429).

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
