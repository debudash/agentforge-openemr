# Alerts and on-call response

Three alerts on the co-pilot's metrics, what each one means, and what the person
holding the pager does about it. A fourth is specific to this agent's design.

Companion documents: [KEY_METRICS.md](KEY_METRICS.md) (where the baselines come from),
[ARCHITECTURE.md](ARCHITECTURE.md) (what the signals describe), [api/README.md](api/README.md)
(how to read `/metrics` and `/ready` by hand), [AUDIT.md](AUDIT.md) (finding C3a, which is the
security-side alerting gap these do **not** close).

---

## 1. The principle these thresholds are built on

**Alert on departure from the measured baseline, not on the aspirational target.**

The PRD sets p95 within 10 s for a verified answer. The system measures p95 19.8 s on the
free-tier model, and `KEY_METRICS.md` records that as a missed target with the reason. An alert set
at the PRD target would therefore fire on every request, forever, on a system behaving exactly as
designed and documented.

That is the classic way to make a pager useless. An on-call engineer woken by a known condition
learns within a week to ignore the channel, and then misses the real one.

So each threshold below is set against **what this system actually does today**: wide enough that
normal operation is silent, tight enough that a real regression is loud. The PRD target is tracked
as an SLO in `KEY_METRICS.md`; it is a roadmap item, not a pager condition.

Two rules apply to every alert here:

- **No percentile is evaluated below n = 20** in the window. A p95 over five requests is noise, and
  firing on it trains people to distrust the alert. Below the minimum the alert reports
  *insufficient data*, which is a distinct state from *healthy*.
- **Every alert names the first command to run.** An alert that says only "latency is high" makes
  the responder start from nothing at the worst possible moment.

---

## 2. Where the signals come from

All four alerts read `GET /metrics` on the agent service (HMAC-signed; see
[api/README.md](api/README.md)). Administrators see the same data rendered in the **CopilotHealth**
tab inside OpenEMR.

| Alert | Field in `/metrics` | Wired today |
|---|---|---|
| A1 latency | `latency_ms.answer_ms.p95`, `latency_ms.brief_ms.p95` | Yes |
| A2 error rate | `counters.answer_state_*` | Yes |
| A3 tool failure rate | source read outcomes per domain | **No — see §7** |
| A4 verification removal | `counters.claims_kept`, `claims_removed`, `removed_*` | Yes |

**Be precise about what "wired" means here.** The counters exist and are correct. What does not
exist is anything that *evaluates* a threshold: the counters are in-process and cumulative since
the service last started, so there is no rolling window to compare against and no evaluator to do
the comparing. Section 7 states this plainly rather than implying the alerts are live.

---

## 3. A1 — Answer latency p95 above baseline

| | |
|---|---|
| **Signal** | `latency_ms.answer_ms.p95` |
| **Warning** | p95 above 30 s over a 30-minute window, n >= 20 |
| **Critical** | p95 above 60 s, or p50 above 30 s, over 15 minutes |
| **Baseline it is set against** | p50 6.1 s, p95 19.8 s (golden suite, `KEY_METRICS.md` row 5) |

**Why 30 s and not 10 s.** 19.8 s is the measured p95 and it is dominated by free-tier queueing,
which varies by the hour. 30 s leaves headroom for a bad provider afternoon without hiding a
genuine regression; 60 s is roughly three times baseline and cannot be explained by queueing alone.

**What it means.** Almost always the model provider, not this service. The agent does little work
of its own: a verified answer is at minimum two model calls, and the service spends nearly all of
the elapsed time waiting on the provider.

**What it does not mean.** It is not a correctness signal. A slow answer is still a verified
answer — nothing is streamed, and verification completes before any text is sent. Latency never
degrades safety in this design; it degrades patience.

**On-call response**

1. `GET /ready`. If `model_provider` is not `ok`, this is a provider outage — go to step 4.
2. Read `retries.rate_limited` in `/metrics`. If it is climbing against `answer_state_complete`,
   you are being throttled, which is the common case on a `:free` slug.
3. Open the slowest recent trace in LangSmith by `correlation_id`. The per-step timings say whether
   the time went to the draft call, the tool rounds or the verify call.
4. **If it is the provider:** there is no local fix. Decide between waiting and switching
   `COPILOT_MODEL` to a paid slug — that is a cost decision, so it is the service owner's call, not
   the responder's. Record the window in the incident log.
5. **If it is not the provider** — `/ready` healthy, retries flat, traces showing time spent inside
   the service — that is a genuine regression in this codebase and is worth paging the owner. It
   has not happened to date.

---

## 4. A2 — Error rate above baseline

| | |
|---|---|
| **Signal** | `counters.answer_state_unable_to_answer` over (`complete` + `partial` + `unable_to_answer`) |
| **Warning** | above 10 % over 30 minutes, n >= 20 |
| **Critical** | above 25 %, or any `unable_to_answer` caused by `provider_unavailable` on 5 consecutive requests |
| **Baseline** | 0 unable across the golden suite and live demo traffic to date |

**`access_denied` is deliberately excluded from this ratio.** A refusal to answer about a patient
outside the clinician's panel is the scope guard doing its job, and there is no volume of it that
indicates a fault. Counting it as an error would mean a working security control raises an alarm —
and worse, that someone would eventually "fix" the alarm by weakening the control. The same applies
to off-topic scope statements.

**What `unable_to_answer` actually means.** The agent produced no claim it could stand behind: the
model failed, every drafted claim was removed by the verifier, a source was unavailable, or the
tool loop hit its limit. It is a *safe* failure — the design's preferred outcome over a confident
wrong answer — but a rising rate means the system is refusing work it should be doing.

**On-call response**

1. `GET /metrics` and read the `removed_*` breakdown. If removals are driving the rate, this is a
   model or verifier problem rather than infrastructure — go to A4.
2. If removals are flat, check `/ready` and `retries.draft_failed`. A model failing to return
   parseable output shows up here.
3. Pull three `unable_to_answer` traces in LangSmith. The response carries an explicit reason
   string (`source(s) unavailable: ...`, `tool-call limit reached`, `no claim passed verification`).
   Those three reasons have completely different owners.
4. **Source unavailable** — the fault is in OpenEMR or the network path to it, not the agent. Check
   OpenEMR directly.
5. **Loop exhausted** — questions are getting harder, or the model is looping. Capture examples; it
   is a tuning issue, not an outage.
6. **Nothing passed verification** — treat as critical. Either the model has degraded badly, or a
   change to the verifier is rejecting valid claims. The second is the dangerous one: check whether
   `constraints.py` or `verify.py` shipped recently.

---

## 5. A3 — Tool failure rate

| | |
|---|---|
| **Signal** | source reads returning `error` or `timeout`, over all source reads, per domain |
| **Warning** | above 5 % over 30 minutes, n >= 20 reads |
| **Critical** | above 20 % on any single domain, or any domain at 100 % for 5 minutes |
| **Baseline** | 0 observed failures in the golden suite and demo traffic |

**This alert is not yet evaluable** — the counter does not exist. See section 7. The definition is
written here so the wiring has a specification to satisfy, rather than the other way round.

**Two different failures, deliberately separated.** `SourceStatus.status` distinguishes `ok`,
`empty`, `error` and `timeout`. Only `error` and `timeout` count here.

- **`empty` is not a failure.** A patient with no recorded allergies returns an empty allergy read,
  and that is a true answer about the chart. Counting it would alarm on healthy patients.
- **`tool_invalid_arguments` is counted separately.** That is the *model* calling a tool wrongly,
  not the tool being broken. It needs a prompt or schema fix, not an infrastructure responder. Both
  are recorded; they never share a threshold.

**What it means.** The agent reads OpenEMR through the module's chart reader. Sustained read
failures mean OpenEMR, its database, or the path between them — the agent has no way to break a
single domain while the others keep succeeding.

**On-call response**

1. Identify the failing domain from the per-domain breakdown. One domain failing while the rest are
   healthy points at that query or table, not at the service.
2. `GET /ready`. The `openemr` probe confirms reachability, but note that it only proves OpenEMR
   answers HTTP — a healthy probe with failing reads means the database or a specific query, not
   the host.
3. Check OpenEMR's own error log and the database.
4. Confirm the safety behaviour is intact: responses should be degrading to `partial` with
   `source(s) unavailable` named, not silently omitting data. If a source is failing and answers
   still come back `complete`, **that is the real incident** — escalate immediately. It would mean
   the completeness signal is lying to clinicians, which is worse than the outage itself.

---

## 6. A4 — Verification removal rate (beyond the required three)

The requirements ask for metrics that matter to the specific agent design. Here that is the
verifier: it is the control the whole safety argument rests on, and the only signal that watches
the model's honesty rather than the platform's health.

| | |
|---|---|
| **Signal** | `counters.claims_removed` over (`claims_kept` + `claims_removed`), with the `removed_*` breakdown |
| **Warning** | above 5 % over 30 minutes, n >= 20 claims |
| **Critical** | above 15 %, or **any** `removed_wrong_patient` at all |
| **Baseline** | 104 claims kept, 0 removed in live demo traffic |

**Both directions are informative**, which is unusual and worth stating:

- **Rising** means the model is drafting claims it cannot support. The verifier is catching them,
  so the system is safe — but quality is degrading and users are seeing thinner answers.
- **Stuck at exactly zero across a large sample** deserves a look too. It is the expected result
  here, but it is also what a silently disabled verifier looks like. The unit tests are what
  distinguish those two cases, which is why they assert removals on crafted input rather than
  trusting the live counter.

**`removed_wrong_patient` is critical at a count of one.** Every other removal reason is a quality
signal; this one means the model attempted to cite another patient's record. The turn-scoped
citation rule makes that structurally very hard, so a single occurrence means an assumption has
broken. Page immediately, capture the trace, and treat it as a potential scope-boundary defect
until proven otherwise.

**On-call response**

1. Read the `removed_*` breakdown. The reason code determines the owner.
2. `wrong_patient` — page the owner, preserve the trace, and do **not** restart the service:
   restarting destroys the in-process counters, and the evidence with them.
3. `no_citation` / `restated_without_lookup` rising — model degradation. Compare against a recent
   eval run before changing anything.
4. `recommendation` rising — the model is drifting toward clinical advice and the product boundary
   is holding it back. Worth a prompt review, not a page.

---

## 7. What is not wired, stated plainly

Two of these alerts describe evaluation this system cannot currently perform.

**There is no evaluator and no window.** Counters live in the service process (`telemetry.py`,
`app.py`) and are cumulative since start. Nothing computes a rate over the last 30 minutes, and
nothing compares a value to a threshold. Every "over 30 minutes" above is a specification, not a
running check.

**They reset on restart, and they are single-replica.** A deploy clears every counter, and a second
replica would keep its own separate tallies. This is a deliberate accepted limit — the service
holds session state in memory too, so it is single-replica by design today — but it means an
evaluator reading one replica would be reading a partial view.

**A3's counter does not exist.** `tool_calls` counts calls made; nothing aggregates source read
outcomes by domain. `SourceStatus` already carries `ok`/`empty`/`error`/`timeout` per read, and
`Chart.failed_sources()` already derives the failing ones, so the data is present per request and
simply not tallied. This is a small change, deliberately not made in a rush before submission.

**What closing this properly looks like**, in order of value:

1. Tally source outcomes by domain into `counters`, which makes A3 real. Small, local change.
2. Move counters to a store with time buckets so a rate over a window can be computed. Redis is the
   obvious candidate, and it is also what would let the service run more than one replica.
3. Point an evaluator at it — Grafana, or LangSmith's own alerting on the traces that already exist.

Step 2 is not free. The same store would eventually hold session state, and session state holds
chart data. That puts PHI at rest in a new system and pulls in encryption at rest, a retention
policy, and a subprocessor entry in the audit. It is a real architectural decision rather than an
infrastructure swap, which is why it is written down here instead of being done quietly.

Until then, these definitions are the specification an evaluator would implement, and the
CopilotHealth tab is how a human reads the same numbers.

---

## 8. Deliberate non-alerts

Signals that look alertable and are intentionally not, because each would fire on correct
behaviour:

| Signal | Why there is no alert |
|---|---|
| `answer_state_access_denied` rising | The scope guard working. No volume of correct refusal is a fault. |
| `auth_rejected` rising | Unsigned requests are rejected at the edge by design, and the demo service is public, so scanners produce a steady baseline. A *breach-detection* alert is a different control, and `AUDIT.md` C3a records its absence honestly. |
| Off-topic scope statements | The topic pre-check working. |
| `empty` source reads | A true statement about a chart that has no such records. |
| `sessions_active` | Bounded by how many clinicians are signed in; it carries no health information. |

---

## 9. Severity, and who gets woken

| Severity | Response | Who |
|---|---|---|
| **Warning** | Next business day. Recorded, not paged. | Service owner |
| **Critical** | Within the hour during clinical hours. | On-call engineer |
| **Page** | Immediately, any hour. `removed_wrong_patient`, or a source failing while answers still report `complete`. | On-call engineer, then service owner |

Only two conditions page, and both are correctness failures rather than availability ones. That is
the deliberate bias of this design: a slow or unavailable co-pilot is an inconvenience, because the
chart is still right there in OpenEMR and the clinician can read it directly. A co-pilot that says
something untrue about a patient, or claims a completeness it does not have, is the failure this
whole architecture exists to prevent.

**Assumed rotation.** A demo has no real rota. In deployment this assumes one on-call engineer with
access to Railway, LangSmith and the OpenEMR host, plus a named service owner who can authorise a
model change, since that one carries cost.

---

## 10. How to test each alert

An alert nobody has seen fire is a guess. Each of these can be provoked deliberately:

| Alert | How to provoke it |
|---|---|
| A1 latency | Point `COPILOT_MODEL` at a heavily rate-limited free slug and run the Postman collection's ask request repeatedly. |
| A2 error rate | Stop OpenEMR and ask a question: responses degrade to `partial` / `unable_to_answer` with a named reason. |
| A3 tool failure | The same provocation, observed per domain. This is also the check that A3's counter is wired correctly once it exists. |
| A4 removal | Covered by unit tests rather than live traffic: `copilot/tests/test_metrics_counters.py` asserts that each removal reason maps to a code, including `wrong_patient`. |

A2 and A3 share a provocation but must produce *different* readings from it: errors rise **and**
the failing domain is named. If stopping OpenEMR moves only one of them, the other is miswired.
