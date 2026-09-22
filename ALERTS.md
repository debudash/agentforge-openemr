# Alerts and on-call response

Four alerts on `GET /metrics`. Three are the required ones: latency, error rate, tool failure.
The fourth watches the verifier, which is specific to this agent.

See [KEY_METRICS.md](KEY_METRICS.md) for the baselines, [api/README.md](api/README.md) for reading
`/metrics` by hand, [AUDIT.md](AUDIT.md) C3a for the breach-detection gap these do not close.

## Why the thresholds are not the PRD targets

The PRD wants p95 within 10 s. Measured p95 is 19.8 s on the free-tier model, recorded in
KEY_METRICS as a known miss. An alert at 10 s would fire on every request forever, and whoever
carries the pager would stop reading the channel.

These thresholds track departure from measured behaviour. The PRD target stays an SLO.

Two rules throughout:

- No percentile is evaluated below n = 20. Below that the alert reports *insufficient data*, which
  is not the same as healthy.
- Every alert names the first command to run.

## Signals

| Alert | Field | Wired |
|---|---|---|
| A1 latency | `latency_ms.answer_ms.p95` | Yes |
| A2 error rate | `counters.answer_state_*` | Yes |
| A3 tool failure | source outcomes per domain | No, see §7 |
| A4 removal rate | `counters.claims_kept`, `claims_removed`, `removed_*` | Yes |

Administrators read the same numbers in the **CopilotHealth** tab. "Wired" means the counter
exists. Nothing evaluates a threshold yet — see §7.

## A1 — Answer latency

| | |
|---|---|
| Signal | `latency_ms.answer_ms.p95` |
| Warning | p95 over 30 s across 30 min, n >= 20 |
| Critical | p95 over 60 s, or p50 over 30 s, across 15 min |
| Baseline | p50 6.1 s, p95 19.8 s (KEY_METRICS row 5) |

30 s leaves room for a bad provider afternoon. 60 s is three times baseline and queueing cannot
explain it.

Nearly always the model provider. A verified answer is at least two model calls and the service
spends most of the elapsed time waiting.

Not a correctness signal. Nothing streams, and verification finishes before any text is sent.

**Response**

1. `GET /ready`. If `model_provider` is not ok, provider outage — step 4.
2. Check `retries.rate_limited` against `answer_state_complete`. Climbing means throttling, normal
   on a `:free` slug.
3. Open the slowest trace in LangSmith by `correlation_id`. Step timings show whether it was the
   draft call, the tool rounds or verify.
4. Provider outage: no local fix. Switching `COPILOT_MODEL` to a paid slug costs money, so it is
   the service owner's call. Log the window.
5. `/ready` healthy, retries flat, time inside the service: genuine regression. Page the owner.
   Has not happened yet.

## A2 — Error rate

| | |
|---|---|
| Signal | `answer_state_unable_to_answer` over `complete` + `partial` + `unable_to_answer` |
| Warning | over 10 % across 30 min, n >= 20 |
| Critical | over 25 %, or `provider_unavailable` on 5 consecutive requests |
| Baseline | 0 unable in the golden suite and demo traffic |

`access_denied` is excluded. Refusing a patient outside the clinician's panel is the scope guard
working, and an alert on it would eventually be silenced by weakening the guard. Off-topic scope
statements are excluded for the same reason.

`unable_to_answer` means the agent had no claim it could stand behind: model failure, every claim
removed, a source down, or the tool loop exhausted. A safe failure, but a rising rate means work
is being refused that should succeed.

**Response**

1. Read the `removed_*` breakdown. If removals drive the rate, go to A4.
2. Removals flat: check `/ready` and `retries.draft_failed`.
3. Pull three traces. The reason string is explicit — `source(s) unavailable`, `tool-call limit
   reached`, `no claim passed verification` — and the three have different owners.
4. Source unavailable: fault is OpenEMR or the path to it.
5. Loop exhausted: tuning, not an outage. Capture examples.
6. Nothing passed verification: critical. Either the model degraded or a verifier change is
   rejecting valid claims. Check whether `constraints.py` or `verify.py` shipped recently.

## A3 — Tool failure rate

| | |
|---|---|
| Signal | source reads returning `error` or `timeout`, per domain |
| Warning | over 5 % across 30 min, n >= 20 reads |
| Critical | over 20 % on one domain, or a domain at 100 % for 5 min |
| Baseline | 0 failures observed |

Not evaluable yet — the counter does not exist (§7). Defined here so the wiring has a spec.

`SourceStatus` distinguishes `ok`, `empty`, `error`, `timeout`. Only the last two count.

- `empty` is not a failure. A patient with no allergies returns empty, which is true.
- `tool_invalid_arguments` is counted separately. That is the model calling a tool wrongly, and it
  needs a prompt fix, not a responder.

Sustained failures mean OpenEMR, its database, or the path between. The agent cannot break one
domain while the others succeed.

**Response**

1. Identify the domain. One failing while others are healthy points at that query or table.
2. `GET /ready`. The `openemr` probe only proves HTTP answers. Healthy probe plus failing reads
   means the database or one query.
3. Check OpenEMR's error log and the database.
4. Confirm answers degrade to `partial` naming `source(s) unavailable`. **If a source is failing
   and answers still return `complete`, escalate immediately** — the completeness signal is lying,
   which is worse than the outage.

## A4 — Verification removal rate

The verifier is what the safety argument rests on, and the only signal watching the model rather
than the platform.

| | |
|---|---|
| Signal | `claims_removed` over `claims_kept` + `claims_removed`, with the `removed_*` breakdown |
| Warning | over 5 % across 30 min, n >= 20 claims |
| Critical | over 15 %, or any `removed_wrong_patient` |
| Baseline | 104 kept, 0 removed |

Both directions matter. Rising means the model is drafting claims it cannot support — caught, so
still safe, but answers are thinning. Stuck at zero over a large sample is the expected result and
also what a disabled verifier looks like; the unit tests are what tell those apart.

`removed_wrong_patient` is critical at one. Turn-scoped citations make it structurally hard, so one
occurrence means an assumption broke.

**Response**

1. Read the `removed_*` breakdown. The reason code names the owner.
2. `wrong_patient`: page the owner, keep the trace, do **not** restart — that clears the counters.
3. `no_citation` / `restated_without_lookup` rising: model degradation. Compare against a recent
   eval run first.
4. `recommendation` rising: the model is drifting toward advice and the boundary is holding.
   Prompt review, not a page.

## 7. What is not wired

**No evaluator, no window.** Counters live in the process (`telemetry.py`, `app.py`) and are
cumulative since start. Every "across 30 min" above is a specification, not a running check.

**They reset on restart and are single-replica.** Session state is in memory too, so the service is
single-replica by design today. An evaluator reading one replica would see a partial view.

**A3's counter does not exist.** `tool_calls` counts calls; nothing tallies source outcomes by
domain. `SourceStatus` carries the per-read status and `Chart.failed_sources()` derives the failing
ones, so the data is there and simply not aggregated.

Closing this, in order:

1. Tally source outcomes by domain. Makes A3 real. Small, local.
2. Move counters to a store with time buckets. Redis also unlocks multiple replicas.
3. Point an evaluator at it — Grafana, or LangSmith alerting on the existing traces.

Step 2 is not free. That store would eventually hold session state, and session state holds chart
data. PHI at rest in a new system means encryption at rest, a retention policy and a subprocessor
entry in the audit. An architectural decision, not an infrastructure swap.

## 8. Deliberate non-alerts

| Signal | Why not |
|---|---|
| `access_denied` rising | The scope guard working |
| `auth_rejected` rising | Unsigned requests are rejected by design; a public demo attracts scanners. Breach detection is a different control — AUDIT.md C3a |
| Off-topic scope statements | The topic pre-check working |
| `empty` source reads | True statement about a chart with no such records |
| `sessions_active` | Tracks sign-ins, carries no health information |

## 9. Severity

| Severity | Response | Who |
|---|---|---|
| Warning | Next business day, recorded not paged | Service owner |
| Critical | Within the hour during clinical hours | On-call engineer |
| Page | Immediately. `removed_wrong_patient`, or a source failing while answers report `complete` | On-call, then owner |

Only correctness failures page. A slow co-pilot is an inconvenience — the chart is still in
OpenEMR. A co-pilot that says something untrue, or claims completeness it does not have, is what
this architecture exists to prevent.

Deployment assumes one on-call engineer with Railway, LangSmith and OpenEMR access, plus an owner
who can authorise a model change.

## 10. Provoking each alert

| Alert | How |
|---|---|
| A1 | Point `COPILOT_MODEL` at a rate-limited free slug, repeat the collection's ask request |
| A2 | Stop OpenEMR and ask a question |
| A3 | Same, watched per domain. Also the check that A3's counter works once it exists |
| A4 | Unit tests, not live traffic: `copilot/tests/test_metrics_counters.py` |

A2 and A3 share a provocation and must move independently — errors rise *and* the domain is named.
If only one moves, the other is miswired.
