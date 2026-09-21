# Clinical Co-Pilot: AI Cost Analysis

What the build actually cost, what a seat costs to run, and what has to change architecturally at each
order of magnitude. The projections are built from measured payloads in this repository, not from a
price list multiplied by a user count.

**Basis:** payload sizes measured 2026-09-17 by capturing the exact messages the agent sends
(`copilot/copilot/agent.py`, scripted-model double, fixture chart `pid101`). Loop depth and output sizes
aggregated over 135 recorded case-runs in `copilot/evals/stage1/results/`. Model prices are Anthropic
first-party rates as published 2026-06-24.

Companion documents: [KEY_METRICS.md](KEY_METRICS.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[EVAL_DATASET.md](EVAL_DATASET.md), [AUDIT.md](AUDIT.md).

---

## 1. Actual development spend

| Item | Amount | Basis |
|---|---|---|
| Model spend, eval runs | **$0.00** | 26 recorded runs, 135 case-runs, every one on `nvidia/nemotron-3-super-120b-a12b:free` |
| Model spend, early Sonnet runs | **~$10-15** | Estimated, see below |
| Railway infrastructure | **$0.46** to date, **$0.89/mo** projected | `railway usage`, billing period 2026-09-15 to 10-15 |
| **Total attributable AI spend** | **under $20** | |

The eval-run figure is exact: every results file in `copilot/evals/stage1/results/` records
`agent_model`, and all 26 name the free model. The Sonnet figure is an estimate rather than a
measurement, because the 31-case suite those runs used was retired and its results files with it. Taking
the measured per-unit costs in section 2 and the run history described in KEY_METRICS.md, roughly ten
suite runs, twenty twelve-patient prefetch runs, and a few hundred manual browser questions come to
$10-15.

Infrastructure is negligible, and its shape persists at every scale below: of the $0.46 spent, **97% is
memory** on the three always-on services, 2% CPU, and the rest egress and volume. The `copilot-seeder`
cron costs roughly $0.00003/month.

**The interesting result is not the total, it is why it is that low.** The architecture was designed so
that a weak model cannot produce an unsafe answer: claims are deleted unless they cite a record fetched
in the same turn, clinical flags come from a deterministic rule engine, and patient scope is enforced in
code. That made a free model usable for almost the entire build. The safety design paid for itself in
development, before it ever protected a patient.

---

## 2. Unit economics, measured

Every number in this table came from capturing real messages, not from estimating prompt sizes.

| Unit | Model calls | Input tokens | Output tokens |
|---|---|---|---|
| Rounding brief (one patient) | 1 | 2,724 | 522 |
| Follow-up question | 5 | 8,798 | 160 |

The follow-up decomposes as a topic pre-check (137 in), three tool rounds (2,293 / 2,413 / 2,535 in) and
one structured finalisation (1,420 in). Three rounds is the measured mean across 135 case-runs
(2.83; p50 = 2; p90 = 5, which is the hard cap).

**Cost per unit, before any optimisation:**

| Model | Brief | Follow-up |
|---|---|---|
| Opus 5 ($5/$25 per MTok) | $0.0267 | $0.0480 |
| Sonnet 5 ($2/$10 per MTok) | $0.0107 | $0.0192 |
| Haiku 4.5 ($1/$5 per MTok) | $0.0053 | $0.0096 |

**The single most important number in this document:** of the 8,798 input tokens in a follow-up,
**7,943 (90%) are a byte-identical prefix** — the system prompt (1,082) plus the tool schemas (1,205),
re-sent on every one of the three tool rounds. Prompt caching is **not currently implemented**
(`grep -rn cache_control copilot/copilot/` returns nothing). At a 70% effective cache-read rate a
follow-up falls from $0.0192 to $0.0081, a 58% reduction with no change to output quality.

---

## 3. Why this is not tokens x users

Seven effects break the linear model, four downward and three upward.

**1. Per-request cost falls as you scale.** Cache entries have a short TTL, so a lightly-loaded system
pays full price on nearly every request while a busy one serves the same prefix from cache repeatedly.
The marginal cost of request N+1 is lower than request N. This inverts the usual SaaS assumption that
unit costs are flat and only volume grows.

**2. Briefs can become a batch workload, but only above a certain scale.** A brief is generated when the
clinician first opens the panel, inside a 90-second budget (`prefetch_budget_s`,
`prefetch_concurrency=12`), and is then reused until the chart behind it changes — keyed by patient,
chart fingerprint and model. Reopening the panel on an unchanged list costs nothing, measured at 19.6 s
to generate against 0.01 s to reuse. The table below assumes one open per clinician per day, so it was
already counting the cheap case; before the cache, a clinician who reopened the panel four times a day
paid four times the brief cost, which the table would have understated.

Tomorrow's rounding list is knowable the night before — this repository already runs a nightly job that
proves it, the `copilot-seeder` cron. Moving brief generation to an overnight batch keyed off tomorrow's
appointments makes it eligible for the Batch API's **50% discount** and removes the morning demand spike
entirely. That is worth building at 1,000 users and not worth building at 100.

**3. Cost is bounded per patient, not proportional to patient complexity.** `facts_pack` caps everything
it sends: 20 rule flags, 12 medications, 8 disorders, 10 compliance signals; `get_labs` caps at 30 rows
(200 hard), `get_encounters` at 10. A patient with a 2,000-row chart costs the same as one with 20 rows.
A hospital's sickest patients do not cost more, so there is no adverse selection on price — unusual, and
a direct consequence of caps that were put there for grounding reasons in the first place.

**4. The loop cap bounds the worst case.** `max_iterations=5` means a single question can never cost
more than about 1.7x the mean. Per-seat pricing needs a bounded tail, and most agent designs do not have
one.

**5. Failure amplification is real and already visible.** The mean is 2.83 iterations against a p50 of 2:
the tail does disproportionate work. The forced re-lookup path — added to fix the memory-regurgitation
bug — deliberately spends a second pass when a model answers without a lookup. That is a safety feature
with a cost, and it will be a larger share of the bill on a weaker or cheaper model.

**6. The data plane becomes the constraint before the model does.** AUDIT.md P3 measured eight
sequential FHIR calls at 11.4 seconds. At 150,000 charts a day, reading through OpenEMR's service layer
is the binding limit, and the fix is a data-architecture change, not a model change.

**7. Verification does not scale with cost.** The verifier, the five-rule constraint engine and the
four-layer scope check are deterministic code. They cost effectively nothing per request and they do not
get more expensive at volume. A design that used an LLM-as-judge on every response for the same
guarantee would be paying roughly double at every tier in the next section.

---

## 4. Projections and required architecture

Workload assumption: a hospitalist carrying **15 patients** with **3 follow-up questions each**, 22
working days per month. The demo's 5-patient list is a cost-and-time concession, not a clinical figure
(USER.md section 1.1). At that load a seat costs **$22.52/month** naive on Sonnet 5 and **$9.22/month**
optimised — a useful anchor against any per-seat price.

| Users | Patients/day | Model calls/day | Naive (Sonnet 5) | + cache + batch | + Haiku tiering |
|---|---|---|---|---|---|
| 100 | 1,500 | 24,000 | $2,252/mo | $922/mo | $572/mo |
| 1,000 | 15,000 | 240,000 | $22,524/mo | $9,223/mo | $5,718/mo |
| 10,000 | 150,000 | 2,400,000 | $225,245/mo | $92,233/mo | $57,185/mo |
| 100,000 | 1,500,000 | 24,000,000 | $2,252,448/mo | $922,332/mo | $571,846/mo |

### 100 users — the constraint is not cost

$922/month optimised. Infrastructure is roughly $150/month, so **the model is 85% of the bill** and
server-sizing instinct is the wrong instinct here.

What actually breaks first is the single-process design: `SessionStore` holds prefetched charts in
process memory, so a second replica has a cold cache and a restart loses every session.

- Move the session store to Redis; make prefetch idempotent and shared across replicas
- **Implement prompt caching** — the highest-value change in this document, 58% off follow-ups for a few
  lines of `cache_control`, no quality tradeoff
- Connection pooling to OpenEMR and MySQL
- Close the known harness gap: the eval runner bypasses the 60-second deadline enforced in
  `SessionStore.ask` (EVAL_DATASET.md section 4)

### 1,000 users — the morning spike

15,000 briefs land between roughly 06:30 and 08:00 as clinicians open their panels. A semaphore of 12
per process does not survive that, and provider rate limits bind before compute does.

- **Move brief generation to an overnight batch job** keyed off tomorrow's appointment list. This is the
  step change: 50% off briefs, and the spike disappears because briefs become a precomputed artifact the
  panel reads rather than a live call
- Real job queue and worker pool, replacing the in-process semaphore
- Per-tenant token budgets and quota isolation, so one busy hospital cannot exhaust another's throughput
- Committed or provisioned throughput with the provider
- Per-tenant cost attribution — KEY_METRICS.md section 5 already declares token accounting as an open
  gap, and this is the scale at which that gap starts costing real money

### 10,000 users — the data plane, and model tiering

$92K/month optimised, $57K with tiering. Two changes dominate.

**Stop reading through OpenEMR.** 150,000 chart reads a day through the service layer will not hold.
Replicate into a denormalised read store (CDC or a read replica) shaped like `facts_pack`, so the agent
never touches the live OLTP database. This also removes the agent as a source of load on the EHR, which
is what a hospital will actually ask about.

**Tier the models per step, not per product.** The topic pre-check is 137 tokens of trivial
classification and currently runs on the same model as clinical synthesis. Tool-round selection is
similarly mechanical. Moving both to Haiku 4.5 and reserving Sonnet 5 for the finalisation step is
roughly a further 38% — the figure in the last column above.

Also required at this tier: a semantic cache for repeated questions across clinicians on the same
patient; audit-log storage sized deliberately, since every claim and citation is retained; and the eval
suite promoted to a hard CI gate, because a one-line prompt change now moves six figures a year.

### 100,000 users — unit economics versus seat price

$572K/month optimised, which is roughly $5.72 per seat per month against a product that would likely
sell for $40-80. That is a defensible gross margin, but tokens are now a line item the CFO reads.

- A fine-tuned small model for the high-volume, low-judgment steps (extraction and citation binding),
  with a frontier model reserved for synthesis and anything the rule engine flags
- Dedicated capacity rather than per-token pricing
- Regional data residency and per-tenant isolation
- The eval suite is now the moat: it is what makes swapping in a cheaper model at this volume a
  measurable decision rather than a gamble

The structural advantage at this tier is that **the safety layer is free**. Scope enforcement, claim
verification and the clinical rule engine are deterministic; they cost the same at 100,000 users as at
two. Every dollar of optimisation goes into the model budget without touching the guarantees.

---

## 5. The levers, ranked

| Lever | Saving | Quality cost | Effort |
|---|---|---|---|
| Prompt caching | ~58% of follow-up input | none | low |
| Overnight batch for briefs | 50% of brief cost | none, briefs are already precomputed | medium |
| Haiku for topic check and tool rounds | ~38% of the remainder | needs an eval pass to confirm | medium |
| Denormalised chart store | latency and EHR load, not tokens | none | high |
| Fine-tuned extraction model | large, at 100K scale only | significant, needs a full eval | high |

Caching first. It is free money, it is not implemented, and nothing else on the list changes behaviour
as little.

---

## 6. What would change these numbers

Stated plainly, because a projection without its assumptions is a guess with a table around it.

| Assumption | Status | Effect if wrong |
|---|---|---|
| 4 characters per token | **Estimate.** No Anthropic credential was available to run `count_tokens` | +/-15% on every figure |
| 15 patients, 3 questions each | **Assumption.** Not measured against real clinician behaviour | Linear; the dominant uncertainty |
| Fixture chart is representative | **Partly.** Real charts are larger, but `facts_pack` caps the payload | Small, bounded by the caps |
| Three tool rounds per question | **Measured** (mean 2.83 over 135 runs) on a weak model | A stronger model should need fewer, reducing cost |
| 70% effective cache-read rate | **Estimate.** Depends on traffic density and cache TTL | Direct on the caching lever |
| Prices as of 2026-06-24 | Cached from the pricing reference | Direct |

The largest single uncertainty is the workload assumption, not the token arithmetic. One hospitalist,
observed for a week, would collapse most of the error bar — the same measurement KEY_METRICS.md already
names as the open gap for the time-saving metric. One study closes both gaps.
