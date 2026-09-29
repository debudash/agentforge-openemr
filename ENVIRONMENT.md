# Environment variables

Every variable the co-pilot reads, what it does, and what it is set to in this build. Defaults are
read out of the code, not remembered: agent from [`copilot/copilot/config.py`](copilot/copilot/config.py),
module from [`interface/.../src/Config.php`](interface/modules/custom_modules/oe-module-copilot-agent/src/Config.php).

**Nothing here is required to grade the work.** The eval gate runs with every variable unset —
no key, no network, no services (see [EVAL_GATE.md](EVAL_GATE.md) §4). Variables matter for
*running* the co-pilot, not for checking it.

## Two processes, two places

| | Reads | Configured by |
|---|---|---|
| **Agent service** (Python, FastAPI) | `COPILOT_*`, provider keys, `LANGSMITH_*` | `copilot/.env` (gitignored; copy [`copilot/.env.example`](copilot/.env.example)) |
| **OpenEMR module** (PHP) | a small overlapping set | environment, **or** `sites/<site>/copilot-config.php` |

Where both read a variable with the same name (`COPILOT_SHARED_SECRET`, `COPILOT_COMPARISON_HOURS`)
they must agree. The module prefers the environment and falls back to the config file, which is how
Railway keeps its values on the persistent volume rather than in the image.

**Secrets are never committed.** `copilot/.env`, `copilot/.local-*` and `sites/*/copilot-config.php`
are all gitignored. Passwords and the shared secret are shared on request so they can be rotated
without touching git history.

---

## The ones you actually set

Nine variables decide how this behaves. Everything after this table has a working default.

| Variable | This build | What it does |
|---|---|---|
| `COPILOT_PROVIDER` | `openrouter` | `anthropic` or `openrouter`. Must be on the allowlist below |
| `COPILOT_MODEL` | `google/gemini-2.5-flash-lite` | The agent. Chosen after ten candidates were run through the agent's own prompts |
| `COPILOT_VISION_MODEL` | `google/gemini-2.5-flash-lite` | Reads lab PDFs and intake forms. Empty falls back to `COPILOT_MODEL` — which fails if that model cannot see images |
| `COPILOT_JUDGE_MODEL` | `anthropic/claude-sonnet-5` | Grades the eval rubrics offline. Deliberately a different family from the agent. Never on a request path |
| `OPENROUTER_API_KEY` | *(secret)* | Or `ANTHROPIC_API_KEY` for the direct provider |
| `COPILOT_SHARED_SECRET` | *(secret)* | HMAC secret for every module→agent call. **Both processes need the same value** |
| `COPILOT_AGENT_URL` | `http://127.0.0.1:8600` | Where the module finds the agent. Railway: `http://copilot-agent-v82.railway.internal:8600` |
| `COPILOT_ALLOWED_MODELS` | gemini, sonnet, two `:free` slugs | Fail-closed allowlist. **A model not on this list is refused**, so adding a model means adding it here too |
| `COPILOT_DEMO_TOOLS` | `1` on the demo deployment | Turns on the Demo Data tab. Off means the tab does not render *and* its actions refuse |

> The allowlist is the one that bites. Deploying a new model without adding it here refuses every
> call and the app looks broken rather than degraded.

---

## Agent service — full list

Read by `copilot/copilot/config.py`.

### Model gateway (PRD PHI1)

| Variable | Default | Purpose |
|---|---|---|
| `COPILOT_PROVIDER` | `anthropic` | Provider to call |
| `COPILOT_MODEL` | `claude-sonnet-5` | Agent model |
| `COPILOT_JUDGE_MODEL` | *(empty)* | Eval judge; empty means the agent's model |
| `COPILOT_VISION_MODEL` | *(empty)* | Document reader; empty means the agent's model |
| `COPILOT_ALLOWED_PROVIDERS` | `anthropic` | Allowlist, comma-separated |
| `COPILOT_ALLOWED_MODELS` | `claude-sonnet-5` | Allowlist, comma-separated |
| `COPILOT_ALLOWED_ENDPOINTS` | `https://api.anthropic.com` | Allowlist, comma-separated |
| `ANTHROPIC_API_KEY` | *(empty)* | Provider key |
| `OPENROUTER_API_KEY` | *(empty)* | Provider key |
| `COPILOT_REASONING` | `off` | `off`/`default`/`low`/`medium`/`high`. Reasoning models otherwise spend the output budget on hidden thinking and return nothing |
| `COPILOT_MAX_OUTPUT_TOKENS` | `12000` | Per call |
| `COPILOT_MODEL_TIMEOUT_S` | `40` | Per model call |

### Document reading (Week 2)

| Variable | Default | Purpose |
|---|---|---|
| `COPILOT_MAX_DOCUMENT_PAGES` | `6` | Pages sent to the vision model |
| `COPILOT_MAX_DOCUMENT_BYTES` | *(empty)* | Size ceiling; empty means the service default |
| `COPILOT_VISION_RATE_LIMIT_RETRIES` | `1` | Retries on 429 before the document is reported unread. Three backoffs are 56 s of a clinician waiting for something that is not coming |

### Guideline retrieval (Week 2)

| Variable | Default | Purpose |
|---|---|---|
| `COPILOT_GUIDELINES_DIR` | *(empty)* | Corpus location; empty means the bundled corpus |
| `COPILOT_EMBED_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Dense retrieval. `none` keeps BM25 only and downloads nothing |
| `COPILOT_RERANK` | `local` | `local`, `cohere` or `none` |
| `COPILOT_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Local cross-encoder |
| `COHERE_API_KEY` | *(empty)* | Needed only for `COPILOT_RERANK=cohere` |
| `COPILOT_COHERE_RERANK_MODEL` | `rerank-v3.5` | Hosted reranker |
| `COPILOT_RETRIEVAL_TOP_K` | `3` | Chunks returned |
| `COPILOT_RETRIEVAL_CANDIDATES` | `10` | Chunks reranked |

### Agent behaviour

| Variable | Default | Purpose |
|---|---|---|
| `COPILOT_TOPIC_CHECK` | `1` | Is this follow-up about this patient's record? Off sends "how is the weather" to the tools |
| `COPILOT_MAX_ITERATIONS` | `5` | Tool rounds before the answer is forced to `partial` |
| `COPILOT_COMPARISON_HOURS` | `24` | Window for "what changed" |
| `COPILOT_RECENT_LAB_DAYS` | `180` | Window for "recent labs" |
| `COPILOT_PREFETCH_CONCURRENCY` | `12` | Briefs generated at once. Lower it on rate-limited free slugs |
| `COPILOT_PREFETCH_BUDGET_S` | `90` | Budget for prefetching a rounding list |
| `COPILOT_ANSWER_DEADLINE_S` | `60` | A follow-up past this reports "unable to answer" rather than hanging |
| `COPILOT_BRIEF_CACHE` | `200` | Cached briefs, keyed by chart fingerprint and model |
| `COPILOT_SESSION_IDLE_MINUTES` | `120` | Session expiry |

### Trust boundary and observability

| Variable | Default | Purpose |
|---|---|---|
| `COPILOT_SHARED_SECRET` | *(empty)* | HMAC secret. Unset means every request is refused |
| `COPILOT_SIGNATURE_SKEW_S` | `300` | Clock skew tolerated on a signed request |
| `COPILOT_OPENEMR_URL` | *(empty)* | For the `/ready` probe only. The agent never calls OpenEMR in normal operation — data flows inward — so it cannot infer this, and `/ready` reports the dependency unchecked when it is unset |
| `LANGSMITH_TRACING` | `false` | Tracing on/off |
| `LANGSMITH_API_KEY` | *(empty)* | LangSmith key |
| `LANGSMITH_PROJECT` | `openemr-copilot` | Trace project |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com` | LangSmith endpoint |
| `COPILOT_TRACE_REDACT` | `false` | Hide prompts and outputs in traces. Document images and extracted fields are more sensitive than structured fields, so a real deployment sets this |

---

## OpenEMR module — full list

Read by `Config::load()`, from the environment first and then `sites/<site>/copilot-config.php`.

| Variable | Default | Purpose |
|---|---|---|
| `COPILOT_AGENT_URL` | `http://127.0.0.1:8600` | Where the agent is. Docker Desktop: `http://host.docker.internal:8600` |
| `COPILOT_SHARED_SECRET` | *(empty)* | Must match the agent's |
| `COPILOT_COMPARISON_HOURS` | `24` | Must match the agent's |
| `COPILOT_REQUEST_TIMEOUT_S` | `75` | Module→agent HTTP timeout. Above the agent's own deadline, so the agent answers first |
| `COPILOT_LAB_HISTORY_DAYS` | `1095` | How far back the chart read goes for labs |
| `COPILOT_ENCOUNTER_HISTORY_DAYS` | `1825` | Same, for encounters |
| `COPILOT_DEMO_TOOLS` | `0` | Demo Data tab. Never set this on an instance holding real charts |

`sites/<site>/copilot-config.php` is a plain PHP file returning an array, and is gitignored:

```php
<?php
return [
    'COPILOT_AGENT_URL' => 'http://host.docker.internal:8600',
    'COPILOT_SHARED_SECRET' => '...',
    'COPILOT_DEMO_TOOLS' => '1',
];
```

It exists so the local stack can be configured without recreating containers, and so Railway keeps
the values on its persistent volume rather than in the image.

---

## Patient dashboard

The new dashboard ([PATIENT_DASHBOARD_MIGRATION.md](PATIENT_DASHBOARD_MIGRATION.md)) is a static
build, so its variables are read when it is built, not at runtime. Set them in
`dashboard/.env.local` (gitignored; see `dashboard/.env.example`), or in the environment of
`deploy/railway/build_openemr_image.sh`, which requires the first.

| Variable | Default | Purpose |
|---|---|---|
| `VITE_SMART_CLIENT_ID` | *(empty)* | The instance's public OAuth client for the dashboard. Compiled into the app, so each instance needs its own build |
| `VITE_OPENEMR_SITE` | `default` | OpenEMR site, for the Co-Pilot links |

Two OpenEMR globals (Admin > Globals > Appearance, stored in the `globals` table) turn it on in
the chart:

| Global | Default | Purpose |
|---|---|---|
| `patient_dashboard_renderer` | `legacy` | `smart_app` shows the new dashboard in place of the old cards. `legacy` is the rollback |
| `patient_dashboard_smart_client_id` | *(empty)* | Same ID as `VITE_SMART_CLIENT_ID`. Empty keeps the old cards |

Registering the client (redirect and launch URL `https://<host>/public/dashboard/`) is in
[deploy/railway/README.md](deploy/railway/README.md), "Patient dashboard".

---

## Where these are set in practice

| Setting | Local | Railway |
|---|---|---|
| Agent variables | `copilot/.env` | Service variables on `copilot-agent` |
| Module variables | `sites/default/copilot-config.php` | The same file, on the volume |
| Agent address | `http://host.docker.internal:8600` | `http://copilot-agent-v82.railway.internal:8600` |
| Demo tools | on | on, for grading |

Setup is in [README.md](README.md) ("First-time setup", then "Week 2"); the deployment is in
[deploy/railway/README.md](deploy/railway/README.md).
