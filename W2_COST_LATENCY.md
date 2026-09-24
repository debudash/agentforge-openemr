# Week 2 cost and latency

What the Week 2 build cost, what it would cost in production, what it takes in time, and where
the time goes. Measured figures are from the local stack and say so; projections say so too.
Week 1's figures and method are in [COST_ANALYSIS.md](COST_ANALYSIS.md).

The models changed mid-week. Stages 1 to 7 ran on OpenRouter `:free` slugs at zero cost and
could not complete a live document read; from stage 8 the agent and the vision model are
`google/gemini-2.5-flash-lite` and the eval judge is `anthropic/claude-sonnet-5`. Figures below
are labelled with which of the two they came from.

## Development spend

| Item | Spend |
|---|---|
| Free-tier phase, stages 1 to 7 | **$0.** Agent, judge and vision on `:free` slugs; the per-account quota ran out during stage 3, which is why live extraction stayed unproven until the switch |
| Model bench, ten candidates through the agent's own code | part of the $0.79 below; not billed separately |
| Paid phase: building, the walkthrough runs, manual testing, one judged gate | **~$0.88** (credit-balance delta over 2026-09-23/24) |
| Whole account to date, Week 1 and Week 2 together | **$9.41 of $30** |
| Deploying Week 2 and proving it live | **$0.09** -- the agent image, the module ship, and the generate-read-refuse cycles that found three version-skew bugs |
| Retrieval | **$0.** BM25 and two local models (all-MiniLM-L6-v2, ms-marco-MiniLM-L-6-v2), about 90 MB each, downloaded once |
| Infrastructure | Railway, unchanged in shape from Week 1: **$0.89/month** projected across all services (`COST_ANALYSIS.md`). Week 2 added no service -- the agent image grew by roughly 400 MB for CPU torch and the two prefetched retrieval models, which costs build time rather than runtime |

## What a unit of work costs

`google/gemini-2.5-flash-lite` is $0.10 per million input tokens and $0.40 per million output.
Per-call token counts are not instrumented, so the rows below are computed from the request
shape and then checked against a whole walkthrough's credit-balance delta, which is the honest
bound: **$0.011 for 30 checks and about 15 model calls, two of them document reads.**

| Unit | Model input | Model output | Cost |
|---|---|---|---|
| Read one two-page lab report | ~4,500 tokens | ~1,000 tokens | **~$0.0009** |
| Read one one-page intake form | ~2,500 tokens | ~800 tokens | ~$0.0006 |
| Brief | ~3,000 tokens | ~1,200 tokens | ~$0.0008 |
| Follow-up question (topic check, one tool round, answer) | ~6,000 tokens | ~1,000 tokens | ~$0.001 |
| Guideline search | none | none | $0 (local) |
| Click-to-source page | none | none | $0 (rendering only) |
| Eval gate, 74 cases, judged on `claude-sonnet-5` | — | — | the largest single line item; runs on a push, not on a request |

A hospitalist opening ten charts a day with one new document each is about **$0.02 a day** in
extraction, against the $0.30 projected earlier on a Sonnet-class vision model — the model switch
is a thirtyfold cut, and it is what moved metric 12 in [KEY_METRICS.md](KEY_METRICS.md) from a
projection to a measurement. The Week 1 scaling analysis (100 / 1K / 10K / 100K users) still holds; Week 2 adds
a per-document term to it rather than changing its shape.

**Per seat, per month, in production.** Twenty working days at $0.02 is **$0.44 a month** of
document reading per clinician. Week 1 costed a seat at $9.22/month optimised on Sonnet 5 for the
briefs and follow-ups (`COST_ANALYSIS.md`), so Week 2 adds roughly **5 %** to the per-seat bill and
the shape of the cost does not change: the model is still the bill, and infrastructure at
$0.89/month across all services is a rounding error beside it. At 100 seats that is about
$966/month, of which document reading is $44.

Two caveats, both load-bearing. This assumes one new document per chart per day -- a ward taking
outside records in bulk would pay more, linearly. And the eval gate is the largest single model
cost in this project today, because it runs judged on a push rather than per request; that is a
development cost, not a production one, and it does not scale with seats.

## Latency, measured

| Path | Measured | Note |
|---|---|---|
| Supervise, all runs | **p50 4.4 s, p95 30.5 s, p99 47.0 s** | `/metrics`, `supervise_ms`, n = 41 |
| Supervise, nothing unread | the p50 | chart read by the module plus one round trip; the brief is cached |
| Supervise, two unread documents, both read | the p95 tail | two vision calls, then the chart is re-read and the brief regenerated |
| Vision extraction, one document | **p50 9.4 s, p95 10.4 s** | `/metrics`, `extract_ms`, n = 4. Tight, because the work is one structured call over a fixed number of page images |
| Whole 30-check walkthrough (`usecases/journey.py`) | **~4 min** | generate, supervise, six follow-ups, refusal cases, purge |
| Guideline search, first call | 23.2 s | one-time model download; the image now prefetches both models at build |
| Guideline search, warm | **0.06 s** | BM25 + dense + cross-encoder over 20 chunks |
| Page render with quote boxes | under 1 s | pypdfium2, no model |
| Eval gate, 74 cases | ~10 s unjudged | no model, no network; the judged run is bounded by the judge |
| Week 1 brief and answer | p50 6.1 s, p95 19.8 s | unchanged, from `KEY_METRICS.md` |

The supervise row is a real percentile over 41 runs; extraction over 4; the rest are one or two
samples each, except the walkthrough, which has run about a dozen times. **The p95 misses its 30 s
target** -- 30.5 s against 30 s, which is a miss by half a second and still a miss. It is recorded
as one in [KEY_METRICS.md](KEY_METRICS.md) row 10 rather than rescoped: a run that reads two
documents and then regenerates the brief is three model calls in one request, and that shape is
what the tail measures.

**Reliability, measured rather than impressionistic.** 38 documents read, **2 failed** -- about 5 %,
not the "one in five" earlier drafts of this document claimed from early free-tier testing. A
failure is reported as unread; nothing is guessed. The two failures are `supervise_documents_failed`
in `/metrics`.

## Where the time goes

1. **The model provider, and it is not close.** A vision read measures **9.4 s at p50** against a
   whole supervise run's 4.4 s p50 -- so a chart with a document in it is dominated by the read, and
   a chart with two is dominated by two of them. Everything the module and the agent do around it --
   listing documents, reading their bytes, the signed round trip, persisting results, re-reading the
   chart -- is under a second in total. **There is no second bottleneck worth optimising until this
   one changes**, and it is not ours to optimise: it is one structured call to a provider.
   A failure is reported as unread, never guessed.
2. **The round trip through the module.** Supervise is: list documents, read their bytes, one
   request to the agent, persist, re-read the chart, a second request. Two of those steps are
   OpenEMR database work and are cheap; the second agent request regenerates the brief.
3. **The brief itself.** One structured call over a deterministically packed facts sheet, with a
   second only when the first fails validation. A follow-up question costs more than a brief does:
   the topic check, at least one forced tool call, then the answer. The brief cache means a chart
   that did not change costs nothing; a chart that gained a document is a new brief by design, so
   a supervise run that reads a document pays for two — one before the document, one after.
4. **A refused document costs nothing after the first time.** A document that names another
   patient or that nothing could be read from is recorded as refused beside the document, and
   later opens skip it instead of paying for the read again.

## What would change first

- Instrument tokens per call, keyed by correlation id, so the table above becomes measured rather
  than computed. The provider returns them; the service does not record them yet.
- Return from supervise as soon as extraction is done and let the page poll for the brief, so the
  clinician sees "what changed" before the brief finishes.
- Keep the gate model-free where it can be. The unjudged path costs nothing and runs in ten
  seconds; only the rubric judging needs a model.
