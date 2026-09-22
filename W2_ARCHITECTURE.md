# Week 2 architecture: multimodal evidence agent

**Status: proposal for review.** Decisions are recorded here as made; this becomes the as-built
document as each stage lands.

Week 1 built a grounded reader of structured OpenEMR data. Week 2 adds two things: the agent can
read clinical documents, and work is routed across a three-node graph without losing grounding.

Companion documents: [ARCHITECTURE.md](ARCHITECTURE.md) (the Week 1 baseline this builds on),
[copilot/evals/stage1/GROUNDING_RULES.md](copilot/evals/stage1/GROUNDING_RULES.md) (the ten rules
being extended), [ALERTS.md](ALERTS.md), [AUDIT.md](AUDIT.md).

---

## 1. What changes

| | Week 1 | Week 2 |
|---|---|---|
| Invocation | Top-level `CopilotAgent` tab, rounding list of 5 | Patient-context tab inside the chart; Week 1 tab retained as baseline |
| Input | Structured OpenEMR reads only | Plus lab PDF and intake form via a VLM |
| Agent shape | One loop: brief, then follow-ups | Supervisor + intake-extractor + evidence-retriever |
| Writes | **None.** No DDL, no persistence | Documents and extracted lab results, **written by the module, never the agent** |
| Evidence | Patient record only | Patient record plus a guideline corpus, separately cited |
| Citations | `lab:6001` | `{source_type, source_id, page_or_section, field_or_chunk_id, quote_or_value}` |
| Gate | Local check script before a Railway publish | Pre-push git hook running 50 boolean-rubric cases |

Week 1's loop becomes the **evidence-retriever**. It keeps its verifier, rule engine, four states
and scope boundary unchanged.

---

## 2. Invocation moves into the chart

**As built (stage 0).** OpenEMR dispatches `PatientMenuEvent::MENU_UPDATE` when it builds the
tabs at the top of a patient record — Dashboard, History, Documents and so on. `Bootstrap.php`
listens and inserts a **Co-Pilot** tab after Documents, for hospitalists only. The tab opens
`public/patient.php`, which reads the active patient from the session
(`PatientSessionUtil::getPid()`), never from a query parameter: the entry sets `pid = 'false'` so
the renderer does not append one. As in Week 1, nothing in `standard.json` is edited, so there is
no merge conflict with OpenEMR master.

The page runs its own agent session (`api.php?context=patient`, session id suffixed `|patient`),
so opening a patient never replaces the rounding-list session in the other tab. The brief cache
is shared, so a brief already prefetched from the rounding list is reused instantly.

Two consequences, both load-bearing.

**Patient scope stops being belt-and-braces and becomes the only barrier.** In Week 1 the
hospitalist could only pick from their own rounding list, so `REQ-SCOPE-1` was a second line of
defence behind a UI that offered nothing else. From the patient dashboard, `pid` arrives from the
session, and OpenEMR will happily open any chart — provider assignment is a data attribute, not an
access restriction (`AUDIT.md` S3). `PanelScope` is now the single thing standing between a
hospitalist and a chart outside their panel. It is unchanged in behaviour but promoted in
importance, and the eval suite treats it accordingly.

**Prefetch loses its home, and prefetch was what made the latency defensible.** `KEY_METRICS.md`
records p95 19.8 s against a 10 s target, tolerable only because the brief was computed before the
clinician opened the patient. Invoked per-patient, the clinician now waits for it.

Resolution: **keep both entry points.** The Week 1 tab keeps the rounding list and its prefetch;
the patient-context tab is the Week 2 flow. This is not scope creep — the Week 2 requirements
state that the README must separate Week 1 baseline behaviour from Week 2 multimodal behaviour and
that graders must be able to run the Week 2 flow without guessing. Two distinct entry points is
the clearest form of that separation. The patient tab additionally warms the brief in the
background for patients on today's appointment list, so the common case is still prefetched.

---

## 3. The graph

LangGraph, already a dependency. One supervisor, two workers, explicit handoffs.

```
  doctor opens the Co-Pilot tab in a patient chart
                    |
                    v
            [ SUPERVISOR ]  decides; never touches a chart or a document itself
                    |
      1. any unprocessed documents for this patient?
                    |
         +----------+-----------+
         | yes                  | no
         v                      |
 [ INTAKE-EXTRACTOR ]           |
   upload if needed             |
   VLM extract -> schema        |
   module persists              |
   returns manifest             |
         |                      |
         +----------+-----------+
                    v
      2. [ EVIDENCE-RETRIEVER ]   (the Week 1 agent)
            chart read + facts_pack
            hybrid RAG over guidelines
            draft -> verify -> state
                    |
                    v
      3. supervisor assembles: brief, what changed,
         and the documents behind it with type and load date
```

**Handoff record.** Every edge writes one entry: `from`, `to`, `reason`, `correlation_id`,
`duration_ms`, and the decision inputs (document count, doc types). The supervisor's routing is
therefore replayable from logs alone, which is the requirement's actual test — a supervisor that
cannot be explained is the named pitfall.

**Supervisor has no tools.** It routes and assembles. It cannot read a chart, call a VLM or
retrieve evidence, so it cannot produce an unverified claim. Every claim in the final response
still originates in the evidence-retriever and passes the Week 1 verifier.

**No-new-documents path.** With nothing unread the supervisor hands straight to the retriever.
The brief is then identical to Week 1's, which is a useful property: the Week 2 path degrades
exactly to the Week 1 path.

**As built: the graph pauses while the module writes.** The agent cannot read OpenEMR documents
and must not write to OpenEMR, so the module lists the patient's documents, hands the unread
ones' bytes to `POST /session/{sid}/supervise`, and the graph runs supervisor → intake-extractor
→ supervisor. There the supervisor calls LangGraph's `interrupt`: control returns to the module
with the extractions and a logged handoff "supervisor → module". The module persists through
`DocumentWriter`, re-reads the chart, and calls `/supervise/resume` with the persisted ids and the
re-read chart. The graph resumes from its checkpoint, the retriever generates the brief from that
chart, and the supervisor assembles "what changed": one deterministic sentence per document read,
cited to `doc:<id>`, run through the verifier like every other claim. A document that could not
be read (the free tier's rate limit is the usual reason) gets its own sentence saying so, and the
brief still comes. The supervisor node holds no tools and calls no model; a test asserts it.

---

## 4. Document ingestion

### The contract

```python
attach_and_extract(patient_id: int, file_path: str, doc_type: Literal["lab_pdf", "intake_form"])
    -> ExtractionResult
```

One call does upload, extraction and persistence, so the demo is reproducible from a file on disk.
A seed script places two sample documents for the demo patient.

### Who writes what

The agent stays read-only. It returns validated extraction JSON; the **module** persists it
through a new signed endpoint. This keeps three Week 1 properties intact: the agent holds no
database credentials, PHI4 still holds (the browser reaches neither agent nor model), and every
write lands in OpenEMR's own audit log under the clinician's session.

| Artefact | Destination | Where the hospitalist sees it | FHIR |
|---|---|---|---|
| Source lab PDF | `documents`, category **Lab Report** (id 2) | Patient chart → Documents | DocumentReference |
| Source intake form | `documents`, category **Medical Record** (id 3) | Patient chart → Documents | DocumentReference |
| Extracted lab values | `procedure_order` → `procedure_order_code` → `procedure_report` → `procedure_result` | Patient Results, Lab Overview | Observation |
| Extracted intake values | Sidecar extraction document (JSON) under Medical Record, named against the source document id | Patient chart → Documents, beside the form | DocumentReference |

Source documents go through `DocumentService::insertAtPath()`. The procedure chain has no
service-layer insert, so the module writes it directly via `QueryUtils` — five inserts, one
transaction.

OpenEMR's seeded categories are reused rather than adding a co-pilot category: `categories` is a
nested set, so a new one means nested-set maintenance for cosmetic gain, and a lab PDF belongs
under Lab Report, which is where a clinician looks. A dedicated category can be added later
through Admin → Documents without code.

**Intake extraction is a sidecar document, not a clinical form.** `form_clinical_notes` requires an
`encounter` and a `forms` row, which would both force an auto-created encounter and make the
extraction look like a clinical form entry. A document satisfies "persist derived facts as
appropriate FHIR resources" through DocumentReference while creating nothing that reads as
clinician-confirmed.

**Why the procedure chain and not something simpler.** `ObservationLabService` reads exactly that
chain and is what `FhirObservationService` projects as FHIR Observations. Writing there means
extracted labs appear in FHIR, in OpenEMR's own Lab Overview, and to the Week 1 `ChartReader`
with no new reader code. There is no service-layer insert for `procedure_result`, so the module
writes the chain directly — five inserts, one transaction, `QueryUtils` per the project standard.

**Order attribution.** The extractor reads the ordering provider from the lab document. If it is
an exact match for the signed-in hospitalist, the order is attributed to them, because they really
did order it. Anything else goes to a `Document Import` pseudo-provider. The match is exact and
only against the signed-in user, never fuzzy across all providers, since a misread name would
otherwise attribute an order to the wrong clinician. Either way the result rows carry the
machine-extracted marker: who ordered the test and whether a model read the values are separate
facts, and the chart records both.

**Intake data does not become clinical data.** The intake schema carries current medications,
allergies and family history. Writing those into `lists` would produce allergy and medication rows
indistinguishable from clinician-confirmed ones, which is both a duplicate-record problem and a
patient-safety problem. Intake facts are persisted as a document plus a structured extraction, and
the brief states them as *reported on intake, not reconciled*, with the citation pointing at the
form. A lab result is an observation about the patient; an intake form is an assertion by someone
else, and the architecture keeps that distinction visible.

### What counts as "new"

A document is unprocessed when no extraction record references its `documents.id`. Derived by
query at request time: no watermark table, no agent-side state, correct after a restart, and
correct if someone deletes an extraction to force a re-run.

### Idempotency

`attach_and_extract` on an already-processed document returns the existing extraction rather than
writing a second chain. The requirement is explicit that round-tripping must not create duplicate
or untraceable records, and re-running the demo is the obvious way to create them.

---

## 5. Schemas

Pydantic, strict, in `copilot/copilot/documents/schemas.py`. Every extracted field carries its own
citation — the citation is part of the field, not attached afterwards.

**`LabResult`**: `test_name`, `value`, `unit`, `reference_range`, `collection_date`,
`abnormal_flag`, `citation`, `confidence`.
**`LabDocument`**: `patient_ref`, `report_date`, `performing_lab`, `results: list[LabResult]`,
`page_count`, `citation`.

**`IntakeForm`**: `demographics` (name, dob, sex), `chief_concern`, `current_medications`,
`allergies`, `family_history`, each entry with its own `citation` and `confidence`.

**Unsupported extractions are visible, never silent.** A field the VLM could not locate in the
document is `null` with `confidence: 0` and no citation — it is never omitted from the schema and
never guessed. A field with a value but no resolvable citation is rejected by validation and
reported as an extraction failure. This is the mechanism the requirement asks for: the schema
makes an unsupported extracted fact impossible to present as a supported one.

---

## 6. Citation contract

Week 1 citations were record ids resolved against a per-chart index. Week 2 needs page and quote
detail, and a second source class that is not a patient record at all.

```
{source_type, source_id, page_or_section, field_or_chunk_id, quote_or_value}
```

| `source_type` | `source_id` | `page_or_section` | Resolves against |
|---|---|---|---|
| `record` | `lab:6001` | null | The Week 1 chart index |
| `document` | `doc:412` | `p2` | The stored document plus its extraction |
| `guideline` | `guideline:uspstf-htn-2021` | `§3.2` | The corpus index |
| `rule` | `rule:ALLERGY-1` | null | Rule-engine outcomes |

Week 1 citations keep working: a bare `lab:6001` normalises to `source_type: record` with nulls.

**Bounding boxes.** The overlay derives the box by locating `quote_or_value` in the PDF text
layer, which works for digitally generated PDFs. For a genuinely scanned page with no text layer,
the citation degrades to `page_or_section` and the UI highlights the page rather than a region. The
UI never draws a box from coordinates a model asserted, because an invented box is a false claim
about where evidence came from.

---

## 7. Grounding rules: what extends, and what must not

The ten rules stay. Four need extension for document and guideline sources, and the split that
matters is preserved: anything deterministically checkable stays out of the judge.

| Rule | Extension |
|---|---|
| **1** cite a record | Citable sources now include `document:` and `guideline:`. A claim about the *patient* must still cite `record`, `document` or `rule` — never `guideline` alone. |
| **2** active patient only | Unchanged, and now stricter in effect: a document must belong to the active patient, checked against `documents.foreign_id` before extraction, not after. |
| **3** numbers copied, not derived | An extracted number becomes citable only once it is a stored record. The verifier compares the claim's number to the **persisted** `procedure_result.result`, not to the model's extraction output. A VLM reading "5.4" is a *proposal*; the row is the record. |
| **4** no recommendation | Unchanged and deliberately not relaxed. Guidelines may be quoted as evidence; they may never be applied to this patient as advice. A claim that mixes documented evidence with an action is split or removed. |
| **7** only the rule engine judges constraints | A lab PDF's own `abnormal_flag` is **extracted data, not a constraint judgement**. It is stored and citable as what the report said, but "abnormal" in a response still requires a rule-engine outcome. Where the document's flag and the engine disagree, both are shown. |

Two new rules for this surface:

| # | Rule | Enforced by |
|---|---|---|
| **11** | Every extracted fact presented to the clinician carries a document citation with a page, and extraction confidence is displayed, never hidden. | verifier + UI |
| **12** | Guideline evidence is visually and structurally separated from patient facts in every response. | schema (distinct response section) + judge |

Rules 11 and 12 follow the Week 1 split: 11 is structural and code-enforced, 12 needs a judge for
the presentation half.

---

## 7a. Scope: what is deliberately not built

The Week 2 requirements list five items under Core Deliverables that the body text calls extension
work. Confirmed scope:

| Item | Decision |
|---|---|
| Click-to-source UI plus document preview | **Build.** The bounding-box overlay is required by the citation contract regardless |
| Contextual retrieval improvements | **Build**, as better chunking and domain-specific filters |
| Query rewriting | **Skip.** On a 15-25 chunk corpus there is no recall gap for a rewriter to close, and it puts a model call between what the clinician asked and what is searched -- reintroducing exactly the coupling the Week 1 topic pre-check removes by classifying the question alone |
| Critic agent | **Skip**, because it already exists. The Week 1 verifier deterministically rejects uncited claims and recommendation phrasing, which is what the bullet describes, done structurally rather than by a second model |
| Third document type | **Skip.** The requirements' own pitfall list warns against more types before two work reliably |
| Lab trend widget | **Skip.** Polish on a working slice, not load-bearing for the gate |

This follows the requirement's closing note: the best submissions feel narrower than the spec.

---

## 8. Hybrid RAG

| | Choice |
|---|---|
| Corpus | 15–25 chunks of public-domain US guidance (USPSTF, CDC, NIH) on hypertension, diabetes and lipids, matching the existing fixture charts. Committed as text with source URLs. |
| Sparse | BM25 (`rank_bm25`), in-process, no service |
| Dense | Local `sentence-transformers` embeddings (all-MiniLM-L6-v2), in process. **As built without Chroma**: 20 chunks fit in one array, and a vector store would be a second thing to run and explain for no retrieval gain |
| Rerank | Local cross-encoder by default; Cohere Rerank behind `COPILOT_RERANK=cohere` |
| Fusion | Reciprocal rank fusion over both lists, then rerank, then top 3 |
| Improvements | Section-aware chunking that never splits a recommendation statement, plus a condition filter derived from the chart's own problem list |

Local-first by default so the demo runs offline and costs nothing, with the paid reranker as a
one-variable switch mirroring the vision-model switch. Only the top reranked chunks reach the
answer model, and each arrives with its `guideline:` citation already attached.

**As built.** The corpus is five public-domain sources (three USPSTF recommendation statements,
two MedlinePlus pages), one chunk per `##` section, 20 chunks, each committed with its URL and
retrieval date. The agent's `search_guidelines` tool returns chunks as `guideline:<doc>#<section>`
ids; the model puts what they say in a separate `evidence` list. The verifier checks evidence
under the same rules as claims, plus two of its own: an evidence entry must cite a guideline, and
a claim about the patient may not cite a guideline alone. The unit tests and the eval gate run
retrieval BM25-only with no models (`COPILOT_EMBED_MODEL=none`), so a push never downloads
anything; the service runs the full path, and the two models are fetched at image build.

---

## 9. Vision model

Free OpenRouter vision slug by default; a paid vision model behind `COPILOT_VISION_MODEL`. The
provider allowlist from Week 1 applies unchanged, so an unapproved vision model fails closed
before any document leaves the process.

**What the free tier actually does.** OpenRouter rate-limits free models per account, not per
model. During the stage 3 build three different free vision slugs (Gemma 4 31B, Qwen 3.8 27B,
Gemma 4 26B) all answered `429` after the agent's three backoffs, so the extraction path was
verified fail-closed rather than end-to-end live. The model that reads a document is one
variable, `COPILOT_VISION_MODEL`; the paid slug already on the allowlist is the switch. A model
that does not exist fails the same way with `OpenAIModelNotFoundError` named in the reason.

**Document images are more sensitive than structured fields**, and the free slugs may be logged
provider-side. The default path is therefore demo-data-only, stated in `AUDIT.md`, and the paid
path is what a real deployment would use. `COPILOT_TRACE_REDACT` already exists and extends to
cover document images and extracted fields in traces.

---

## 10. Eval gate

`copilot/evals/stage2/`, 50 cases, boolean rubrics only. Stage 1's 9 golden and 7 behavioural
cases stay untouched and keep running, which is what keeps the Week 1 baseline verifiable.

**As built: no model in the gate.** Every case replays a recorded model output through the real
code. A gate a rate limit can silence is not a gate, and the grader's injected regression must
fail it every time. See [copilot/evals/stage2/README.md](copilot/evals/stage2/README.md).

| Rubric | True when |
|---|---|
| `schema_valid` | Extraction validates against the strict schema, unsupported fields null with confidence 0 |
| `citation_present` | Every clinical claim carries a resolvable citation of the right source type |
| `factually_consistent` | Claim values match the persisted record, not the model's extraction |
| `safe_refusal` | Out-of-scope, out-of-panel and advice requests get the boundary, not an answer |
| `no_phi_in_logs` | No patient identifier, document text or extracted value in any log line |

Case mix across the 50: extraction including deliberately degraded scans, evidence retrieval,
citation integrity, refusals, and missing-data behaviour.

**The gate.** A pre-push git hook runs stage 2 and fails the push when any category drops more
than 5 points against the recorded baseline, or below its absolute threshold. Baselines live in
`copilot/evals/stage2/baseline.json`, committed, so a regression is a diff.

Graders will introduce a regression deliberately and confirm the gate catches it. So the gate is
itself tested: `copilot/evals/stage2/test_gate.py` injects a known break — a verifier that skips
citation checks — and asserts the hook exits non-zero. A gate nobody has watched fail is a guess.

Honest limits of a hook, recorded rather than glossed: it is bypassable with `--no-verify` and
nothing blocks a merge server-side. It was chosen over GitLab CI to keep model quota off every
push and to stay runnable by a grader with no runner.

---

## 11. Observability and cost

Per encounter, one trace tree with the existing `correlation_id` at the root, extended with:
supervisor handoffs and their reasons, per-step latency, tokens and cost estimate per model call
including the VLM, retrieval hits with scores, extraction confidence per field, and the eval
outcome where one applies.

Token and cost accounting was a declared gap in `KEY_METRICS.md` §5. Week 2 closes it, because the
requirement asks for a cost report and because a VLM per page is the first thing here with a cost
that varies by input.

Logs carry ids and counts, never document text, extracted values or patient identifiers. The
`no_phi_in_logs` rubric is what keeps that true under change.

---

## 12. Risks and tradeoffs

| Risk | Mitigation |
|---|---|
| Free VLM extracts poorly from imperfect scans | Schema validation makes it visible rather than wrong: low confidence and null fields surface, and the brief degrades to `partial`. The paid switch exists for a real deployment. |
| Writing to `procedure_*` by hand, with no service-layer insert | One transaction, idempotent on re-run, and read back through `ObservationLabService` in a test so the FHIR projection is proven rather than assumed. |
| Week 1's "writes nothing" claim no longer holds | The claim narrows rather than breaks: the *agent* still writes nothing. `ARCHITECTURE.md` and `AUDIT.md` are updated in the same commit as the first write path, not afterwards. |
| Supervisor becomes a black box | It holds no tools and every handoff is logged with its reason. The routing decision is reconstructable from logs alone. |
| Guidelines drift into advice | Rule 4 unchanged, guideline citations barred from patient-fact claims, and a rubric plus judge check on separation. |
| Latency now visible to the clinician | Both entry points kept; the patient tab warms briefs for today's appointments in the background. |
| Scope check is now the only barrier | Promoted in the eval suite: out-of-panel access is tested from the patient-context entry point specifically, not only from the rounding list. |

---

## 12a. Confirmed operating decisions

Recorded so the build has one place to check rather than a conversation to re-read.

| # | Decision |
|---|---|
| 1 | **The Week 1 top-level tab is frozen.** No document awareness, no new-document badges, behaviour identical to what was submitted. It is the baseline the README must keep separable; Week 2 behaviour lives only in the patient-context tab |
| 2 | **Sample documents are synthetic**, committed under `copilot/evals/stage2/fixtures/documents/`. One clean digital PDF with a text layer, so bounding boxes resolve, and one deliberately scanned-looking image PDF with no text layer, so the page-level citation fallback is exercised rather than assumed |
| 3 | **Demo patient** is the one already on the hospitalist's rounding list on the deployed instance, so the demo flows from the list into the chart. Eval fixtures stay on pid101 / pid202 / pid303 |
| 4 | **Encounter association**: attach to the patient's current encounter when one exists, otherwise leave `encounter_id` at 0. No encounter is ever auto-created — that is clinically consequential and nothing in the requirements asks for it |
| 5 | **The brief gains a "what changed" section** listing new documents with type and load date, above the existing brief. The no-documents path renders no section at all, which is why the Week 1 golden snapshots keep passing |
| 6 | **KEY_METRICS.md keeps its Week 1 five metrics and verdicts intact** and appends a Week 2 section: extraction accuracy, citation resolution rate, retrieval precision, rubric pass rates, cost per document. One file, two labelled parts |
| 7 | **Four of the five rubrics are deterministic.** `schema_valid`, `citation_present`, `factually_consistent` and `no_phi_in_logs` all check code-verifiable facts. Only `safe_refusal` needs judgement, behind a paid-judge env switch, so the gate never depends on a free model being available |

Decision 7 is the one that matters most for the gate. Week 1's free judge was throttled on most
turns and its verdicts discarded; a gate that can be silenced by a rate limit is not a gate.

---

## 13. Implementation sequence

Thin vertical slice first, gate early, breadth last. Each stage ends green.

| # | Stage | Ends when |
|---|---|---|
| 0 | **Done.** Co-Pilot tab in the patient record via `PatientMenuEvent`; scope enforced from session `pid` | Out-of-panel patient is refused and audited from the new entry point (`usecases/test_uc_patient_tab.py`) |
| 1 | **Done.** `documents/schemas.py`; `Citation` gains the v2 fields; verifier learns `document:` and `guideline:` | Week 1 citations still resolve; unsupported fields cannot validate as supported (`test_document_schemas.py`, `test_verify.py`) |
| 2 | **Done.** `DocumentWriter.php`; `api.php` actions `attach` and `persist_extraction` | An extracted lab reads back as a FHIR Observation (`status: preliminary`) and is selectable in Lab Overview (`test_uc_document_writer.py`) |
| 3 | **Built.** `documents/extract.py`, `POST /documents/extract`, `attach` extracts then persists; `/ready` checks the vision model | Proven with a scripted model (`test_extract.py`) and fail-closed live. A successful live extraction is pending a vision model with quota: OpenRouter's free tier is rate-limited per account, and the build exhausted it (§9) |
| 4 | **Done.** `evals/stage2/gate.py`, 50 cases, `baseline.json`, `hooks/pre-push`; `test_gate.py` removes four guards in turn | An injected regression blocks a push (each of the four fails the gate) |
| 5 | **Done.** `IntakeForm` extraction; sidecar document under Medical Record; six intake cases in the gate | Intake facts cited to the form, never merged into `lists` (`test_uc_document_intake.py` asserts the row count is unchanged) |
| 6 | **Done.** `guidelines/retrieve.py`, 20-chunk corpus, `search_guidelines` tool, `evidence` section; six retrieval cases in the gate (62) | Guideline evidence cited separately, barred from patient-fact claims (`test_guidelines.py`, G01–G06) |
| 7 | **Done.** `supervisor.py` (LangGraph, interrupt while the module persists), `/session/{sid}/supervise` and `/resume`, module `supervise` action, patient tab runs it on open | Routing reconstructable from logs (`test_supervisor.py`, `test_uc_supervise.py`); no-documents path degrades to Week 1 |
| 8 | Fill stage 2 to 50 cases, record baselines | All five rubrics above threshold |
| 9 | UI: click-to-source, document preview, bounding-box overlay | A claim opens its page with the quote highlighted |
| 10 | Docs, cost and latency report, deploy behind the Railway gate | Graders can run the Week 2 flow without guessing |

Stage 4 is deliberately fourth. The eval gate is the Week 2 hard gate, and building it against a
working slice means every later stage lands against a gate that already works.
