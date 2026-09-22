# Week 2 cost and latency

What the Week 2 build cost, what it would cost in production, what it takes in time, and where
the time goes. Measured figures are from the local stack on 2026-09-22 and say so; projections
say so too. Week 1's figures and method are in [COST_ANALYSIS.md](COST_ANALYSIS.md).

## Development spend

| Item | Spend |
|---|---|
| Model calls during the build | **$0.** Agent, judge and vision on OpenRouter `:free` slugs; the free tier's per-account quota ran out during stage 3 and stayed out, which is why the live extraction path was verified fail-closed rather than end to end |
| Retrieval | **$0.** BM25 and two local models (all-MiniLM-L6-v2, ms-marco-MiniLM-L-6-v2), about 90 MB each, downloaded once |
| Infrastructure | Unchanged from Week 1 (Railway, one agent service); nothing new deployed yet |

## Projected production cost, per unit of work

Assumptions: a paid vision model at roughly $3 per million input and $15 per million output
tokens (Sonnet class); a two-page report renders to two images of about 1,500 tokens each plus
the text layer; a structured extraction answers in about 1,000 tokens.

| Unit | Model input | Model output | Cost |
|---|---|---|---|
| Read one two-page lab report | ~4,500 tokens | ~1,000 tokens | **~$0.03** |
| Read one one-page intake form | ~2,500 tokens | ~800 tokens | ~$0.02 |
| Guideline search | none | none | $0 (local) |
| Brief after documents | as Week 1 | as Week 1 | as Week 1 (`COST_ANALYSIS.md`) |
| Click-to-source page | none | none | $0 (rendering only) |

A hospitalist opening ten charts a day with one new document each is about $0.30 a day in
extraction on a paid model, and $0 on the free tier. Cohere Rerank, if switched on, adds about
$0.002 per search. The Week 1 scaling analysis (100 / 1K / 10K / 100K users) still holds; Week
2 adds a per-document term to it rather than changing its shape.

## Latency, measured

| Path | Measured | Note |
|---|---|---|
| Supervisor, nothing unread, brief cached | **10.7 s** | one live sample; chart read by the module plus one round trip |
| Supervisor, one unread report, read rate-limited | **10.0 s** | one live sample; one retry then "could not be read", brief still returned |
| Supervisor, one unread report, read succeeds | not measured live | quota; the scripted path takes ~0.4 s for the extraction pipeline without the model call |
| Vision extraction, model call | not measured | never completed on the free tier; three retries of backoff are 56 s, which is why the vision retry budget is now 1 |
| Guideline search, first call | 23.2 s | one-time model download; the image now prefetches both models at build |
| Guideline search, warm | **0.06 s** | BM25 + dense + cross-encoder over 20 chunks |
| Page render with quote boxes | under 1 s | pypdfium2, no model |
| Eval gate, 66 cases | ~10 s | no model, no network |
| Week 1 brief and answer | p50 6.1 s, p95 19.8 s | unchanged, from `KEY_METRICS.md` |

Sample sizes are one or two per row. Treat these as the shape of the numbers, not percentiles.
`/metrics` now records `supervise_ms` and `extract_ms`, so percentiles accumulate in use.

## Where the time goes

1. **The model provider.** A vision read is one structured call over two images; on the free
   tier it is also the thing most likely to fail. Everything else in a supervise run is under a
   second. A paid vision model would make the read a few seconds and reliable.
2. **The round trip through the module.** Supervise is: list documents, read their bytes, one
   request to the agent, persist, re-read the chart, a second request. Two of those steps are
   OpenEMR database work and are cheap; the second agent request regenerates the brief, which is
   the Week 1 cost.
3. **The brief itself.** One structured call over a deterministically packed facts sheet, with a
   second only when the first fails validation. A follow-up question costs more than a brief does:
   the topic check, at least one forced tool call, then the answer. The brief cache means a chart
   that did not change costs nothing; a chart that gained a document is a new brief by design, so
   a supervise run that reads a document pays for two — one before the document, one after the
   chart is re-read.

## What would change first

- Run the vision model on a paid slug for the demo path: it converts "could not be read" into a
  read, and it is one environment variable.
- Return from supervise as soon as extraction is done and let the page poll for the brief, so
  the clinician sees "what changed" before the brief finishes.
- Keep the gate model-free. Nothing above makes it slower, and that is deliberate.
