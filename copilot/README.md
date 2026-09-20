# Clinical Co-Pilot agent

The agent behind the **CopilotAgent** tab in OpenEMR. It prepares a pre-rounding brief for every patient on the signed-in physician's list for the day and answers follow-up questions about the selected patient, with every statement cited to a chart record and verified before display.

Built to `requirements/AgentForge_Clinical_Copilot_PRD.pdf`, within the boundaries of `USERS.md` (§4 NG-1..7, §6 REQ-*) and the findings of `AUDIT.md`.

## How it fits together

```
browser (OpenEMR session)
   │  same origin, session cookie + CSRF header
   ▼
interface/modules/custom_modules/oe-module-copilot-agent/public/api.php     PHP, inside OpenEMR
   ├─ PanelScope     role = Physicians group + provider; scope = patient.providerID == user   (AUDIT S3 fix)
   ├─ ChartReader    OpenEMR services -> compact chart JSON, per-source status               (REQ-MIN-1, REQ-NORM-1)
   ├─ AgentClient    HMAC-signed HTTP to the agent service, correlation id                  (PHI4, NFR6)
   └─ audit          EventAuditLogger rows for open/select/ask/denials                       (FR14, C1c)
   │  private network only
   ▼
copilot/copilot/service/app.py                                             Python, FastAPI
   ├─ session.py     per-user memory; prefetches every brief in the background (90 s budget)
   ├─ agent.py       brief = facts pack -> one structured model call -> verify -> state
   │                 follow-up = tool loop (max 5 rounds) -> finalise -> verify -> state
   ├─ tools.py       10 patient-scoped tools; any other pid is denied
   ├─ constraints.py bounded rule engine: allergy, dose, interaction, lab range, med status
   ├─ verify.py      citation + value + boundary checks; removed claims are reported
   ├─ llm.py         provider allowlist (fail closed) -> ChatAnthropic, traced by LangSmith
   └─ telemetry.py   PHI-free JSON events with correlation ids
```

Each follow-up question is first classified on its own, with no conversation history, by one small structured call (`COPILOT_TOPIC_CHECK`, on by default): a question that is not about a patient's chart or clinical care gets the fixed scope sentence and never reaches the tools. The judgement is made before the history is in play because a model's off-topic judgement degrades once earlier answers are in context. Two structural rules back it up: a follow-up may cite only records a tool returned in that same turn (memory keeps text, not ids), and a turn with no lookup, no claims and no boundary is treated as off-topic whatever the model wrote.

The browser never talks to the agent service or the model. The service holds charts only in memory, only for the session, and only for patients the gateway already authorised; it re-checks the assignment itself and refuses anything else.

## The initial brief

When a patient is selected the brief answers the five questions from the design brief, each section citing records:

1. primary diagnosis (the documented problem chosen by a stated rule, never inferred),
2. co-morbidities (active disorders; findings and social history are separated),
3. recent labs and whether any is outside the **demo** reference range (the record carries no ranges),
4. care-plan adherence signals (open "review due" items, medications past their end date still flagged active, follow-up and immunization gaps),
5. active medications (status derived from end dates) and allergies ("none recorded", never "no known allergies"),

plus the rule-engine outcomes and "items to inspect". Every brief states its comparison window and one of four states: complete for requested scope, partial, unable to answer, access denied.

## Running locally

```powershell
cd copilot
py -3.13 -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then fill in ANTHROPIC_API_KEY, LANGSMITH_API_KEY and the shared secret
.venv\Scripts\python -m uvicorn copilot.service.app:app --host 127.0.0.1 --port 8600 --env-file .env
```

Point the OpenEMR module at it. Environment variables on the container win; otherwise the module reads `sites/default/copilot-config.php` (gitignored), which on the local stack is:

```php
<?php
return [
    'COPILOT_AGENT_URL' => 'http://host.docker.internal:8600',
    'COPILOT_SHARED_SECRET' => '<same value as COPILOT_SHARED_SECRET in copilot/.env>',
];
```

The dev stack keeps `sites/` in a named volume, not a bind mount, so copy the file in (from `docker/development-easy`):

```powershell
Get-Content ..\..\sites\default\copilot-config.php -Raw | docker compose exec -T openemr sh -c "cat > /var/www/localhost/htdocs/openemr/sites/default/copilot-config.php && chown apache:apache /var/www/localhost/htdocs/openemr/sites/default/copilot-config.php"
```

It survives container restarts and recreates (the volume persists); redo it only after a `down -v`.

Book today's rounding list (five appointments per doctor, through the REST API):

```powershell
cd usecases
$env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"
.venv\Scripts\python ..\scripts\seed_appointments.py
```

Sign in as `doctor1` or `doctor2` and open the **CopilotAgent** tab. `admin` is denied the
co-pilot by design (PRD RBAC matrix) and gets a **CopilotHealth** tab instead, showing the
service's counters since it last started.

Health: `GET /health` (process alive; checks nothing else, so a dependency outage never gets a working service killed) and `GET /ready` (probes the model provider endpoint, the LangSmith API and OpenEMR, plus the provider allowlist and shared secret; 503 naming whichever failed). `/healthz` and `/readyz` remain as aliases. Set `COPILOT_OPENEMR_URL` for the OpenEMR probe: the agent never calls OpenEMR in normal operation, so it cannot infer the address. The service refuses to open sessions while not ready.

A runnable API collection covering the whole workflow is in [api/](../api/).

## Testing locally, and the gate in front of Railway

Everything below runs against your laptop only. Nothing in this repository publishes to Railway
except `deploy\railway\deploy_agent.ps1`, and that script refuses to run unless the local checks
have passed on exactly the tree it would upload, and then still asks you to type `DEPLOY`.

```powershell
cd copilot
.\check_local.ps1                 # unit tests + the golden gate against the live model
.\check_local.ps1 -WithGateway    # also the OpenEMR gateway tests (local stack + service up)
.\check_local.ps1 -SkipGolden     # unit tests only, no model calls
```

On success it writes `.local-checks-passed` (gitignored) with the commit and a hash of the
uncommitted `copilot/` diff. To try a change by hand: restart the service on port 8600, sign in
as `doctor1` at https://localhost:9300 and use the tab; the local site config already points at
the laptop service. When you are satisfied:

```powershell
.\deploy\railway\deploy_agent.ps1   # verifies the marker matches, asks for DEPLOY, runs railway up
```

## Tests and evals

```powershell
cd copilot
.venv\Scripts\python -m pytest                                        # 52 unit tests, no key, ~2 s
.venv\Scripts\python -m evals.run_evals --stage stage1 --suite golden # the every-run gate (8 cases)
.venv\Scripts\python -m evals.run_evals --stage stage1                # golden + behavioural (6 scenarios)
.venv\Scripts\python -m evals.run_evals --stage stage1 --judge --langsmith --pace 12   # + judge, upload
.venv\Scripts\python -m evals.run_evals --stage stage1 --suite golden --freeze         # record snapshots
```

Evals are organised per project stage so later stages never mix with this one:

```
evals/common/                 runner, deterministic checks, LLM judge (shared by every stage)
evals/stage1/GROUNDING_RULES.md
evals/stage1/fixtures/charts/ three synthetic charts in the gateway's schema; no OpenEMR needed
evals/stage1/golden/          8 single-turn cases with one right answer: the regression gate
evals/stage1/golden/expected/ frozen snapshots (state, cited records, flags) diffed on every run
evals/stage1/behavioral/      6 multi-turn scenarios graded on tool trace, memory and content
evals/stage1/results/         one JSON per run (gitignored)
```

Verdicts are **pass**, **fail** or **not applicable**: a case whose model call died on a provider rate limit or outage is reported apart and excluded from the pass rate, because it measures the endpoint, not the agent. Golden snapshots should be frozen on the strongest model you run (a reference run) and then compared on every later run; a drift is a regression until someone re-freezes deliberately.

Failure modes, scope denials and verifier removals are covered by the unit tests under `tests/`, which is what they are. Role enforcement and gateway behaviour are tested against a live OpenEMR by `usecases/test_uc_copilot.py`.

Last recorded run (2026-09-16, `anthropic/claude-sonnet-5` via OpenRouter): 31/31 with the judge, supported-claim precision 0.988 on live output, zero wrong-patient citations, state accuracy 1.0. Live round trip: 12 briefs prefetched in 86 s, follow-ups 10-14 s. See `SECURITY_TESTS.md` for the per-control table and open findings.

## Observability

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` to trace every brief, follow-up, tool call and model call under project `LANGSMITH_PROJECT`; the correlation id from the OpenEMR audit row is in each run's metadata. `COPILOT_TRACE_REDACT=true` hides inputs and outputs (PHI7) and keeps the tree, timings and token use. Operational events are one JSON line each on stdout and never contain names, values, prompts or model text. `GET /metrics` (signed) returns counters and p50/p95/p99 latencies.

## Configuration reference

See `.env.example`. The allowlist (`COPILOT_ALLOWED_PROVIDERS/MODELS/ENDPOINTS`) is the PRD PHI1 control: any other configuration fails `readyz` and every session open.

Two providers are supported and selected with `COPILOT_PROVIDER`:

| Provider | Key | Model name form | Endpoint |
|---|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5` | `https://api.anthropic.com` |
| `openrouter` | `OPENROUTER_API_KEY` | `anthropic/claude-sonnet-5` (vendor prefix) | `https://openrouter.ai/api/v1` |

OpenRouter is OpenAI-compatible; the gateway uses `ChatOpenAI` against it. Any model on the allowlist must support **tool calling and structured output** (check `supported_parameters` on openrouter.ai), or the follow-up loop and the brief schema fail. Keep `COPILOT_ALLOWED_MODELS` and `COPILOT_ALLOWED_ENDPOINTS` in step with the provider, as in `.env.example`. Note for a real deployment: the BAA assumption in the PRD (D003) then has to cover OpenRouter as a subprocessor as well as the model vendor (PHI9).

**Free-tier models** (`:free` slugs) work with three adjustments, all in `.env.example`:

- OpenRouter's free tier allows roughly 20 requests a minute, so prefetch concurrency is lowered from the code default of 12. With the five-patient demo list, `COPILOT_PREFETCH_CONCURRENCY=5` fits the whole list in one batch and inside the 90 s budget; raise the list size and the concurrency has to come down again.
- The model wrapper retries HTTP 429 up to three times (Retry-After or 8/16/32 s), then the agent reports "unable to answer" rather than hanging (NFR5). Evals run with `--pace 12` so the judge does not starve the agent of requests.
- `COPILOT_JUDGE_MODEL` lets the evals grade with a different allowlisted model than the agent uses; the judge schema tolerates the spelling variants of yes/no/na that smaller models produce.
- Free routes may log prompts on the provider side. Acceptable for synthetic data only; it is recorded as an accepted finding in `SECURITY_TESTS.md`.

Current configuration: agent `nvidia/nemotron-3-super-120b-a12b:free`, judge `google/gemma-4-31b-it:free`, with `anthropic/claude-sonnet-5` kept on the allowlist so switching back is a one-line change.

## Deploying on Railway

See `deploy/railway/README.md`, "Agent service": the service is built from `Dockerfile.copilot` at the repository root and has no public domain, and the OpenEMR service gets `COPILOT_AGENT_URL=http://copilot-agent.railway.internal:8600` plus the shared secret.
