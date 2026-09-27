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

Clicking the entry opens a tab of its own rather than taking over the chart view, so the brief and
the chart can be read side by side. The patient navbar's renderer drops `target` and emits
`on_click` verbatim, so the handler calls the main screen's own `navigateTab`, naming the tab
`cpapat`, and returns false; where that API is absent the plain href still works. Because
`navigateTab` reuses a tab of that name, clicking Co-Pilot again re-reads whichever chart is now
open. That leaves one new state: a co-pilot tab left open while the clinician moves the chart to
another patient. The page polls the main screen's own current-patient value and, when it no longer
matches the patient it read, says so in a banner naming both, rather than leaving a name on screen
to be misread.

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

**As built: a question runs the same graph as a chart opening.** Stage 3 asks the supervisor to
decide three things, and at first it decided all three for the brief and none of them for a
question: `ask` went straight to the retriever, so a follow-up had no supervisor, no routing and no
handoff record -- and a question asked moments after an upload was answered from the chart as it
had been *before* anyone uploaded anything. Both entry points now build the same document manifest
and enter at the supervisor. The retriever answers where it would otherwise brief; everything else
about the graph is unchanged.

**The supervisor decides evidence retrieval, not the model.** Asked "what evidence supports the
recommendation", the model reached for compliance signals and never opened the corpus -- 0 of 3
live runs. The intent is now read from the question by the supervisor, recorded in the handoff
reason, and passed to the retriever as an instruction: 3 of 3 runs, 2-4 verified guideline entries
each. `needs_evidence()` is a word list rather than a model call, deliberately: a routing decision
that has to be reproducible in a gate cannot itself be a coin flip. Case S07 asserts the decision
through the handoff reason, because a scripted model calls whatever the script says and the reason
is the only place the decision shows.

**The supervisor also scopes a "what changed" question.** Live, it answered with hypertension
diagnosed in 2018 and four long-expired prescriptions, then hit the tool-call limit half way
through. Two causes, one root: a follow-up had no notion of recency at all (`comparison_window` is
the brief's, not the answer's), and every problem and prescription row carries a recent-looking
list date, so a model asked what changed sweeps the chart and reports old news. It also spent one
round per tool, which is how five rounds run out. The supervisor now recognises the question,
records "scoped to what is new" in the handoff, and tells the retriever to answer from
`get_documents` and recent `get_labs` -- what actually arrived. The follow-up prompt separately
says that a round may call several tools at once, which is what the budget assumed all along.

The pre-check remains the gate. It was briefly made advisory, on the theory that it was refusing
terse clinical questions; the logs said otherwise, showing it answering *true* on every refused
"what changed" while the refusal came from the no-lookup rule. Making its verdict non-binding
bought nothing and cost this: asked "how is the weather" with earlier answers in context, the model
looked up the chart, set no off-topic flag of its own, and the turn returned the patient's
medications and labs. Reading the question alone is exactly what makes the check hard to talk
round, which is the reason it reads the question alone. R14 covers it.

A clinician asks this a dozen ways, so the match is on stems -- *chang\*, new, updat\*, differ\** -- rather than a list of the phrasings somebody happened to think of.
"What changed", "whats new", "tell me the changes" and "any updates" all route the same way;
"what medications is she on" does not.

"Anything to report" is judged from the chart, not from this invocation. A follow-up is its own
graph run, so a document read a minute ago during the chart opening leaves no extraction behind in
the question's run and is no longer unread -- which had the co-pilot answer "nothing new since the
brief" moments after reading two documents, reported from the local install. A chart holding
documents has something to report; only a chart holding none is genuinely quiet.

**And when nothing has arrived, it says so.** The supervisor knows whether a document was read
this run or is still waiting, and records "nothing new since the brief" in the handoff when
neither is true. The retriever is then told to confirm with `get_documents` and answer in one
sentence. The failure this avoids is the obvious one: asked what changed on a quiet chart, a model
fills the silence with whatever the chart can offer, and it reads as news. Live, all three
phrasings return no claims and one sentence; after a document arrives, the same questions return
the rows it produced.

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

**As built.** `POST /documents/page` renders the page (pypdfium2) and searches its text layer for
each quote, returning normalised boxes or `found: false`. The module's `page` action checks the
document belongs to the patient, audits the view, and proxies. In the patient tab a document
citation, or a lab row that names its document and page, opens the page inline with the quote
boxed and an "Open original" link to OpenEMR's own document viewer. Lab rows written by
`DocumentWriter` carry `document_id` and the page from the provenance comment, so a value that
came from a report is one click from the report.

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

### The citation contract, and what a click does with it

Every claim that survives verification carries `{source_type, source_id, page_or_section,
field_or_chunk_id, quote_or_value}`. The shape is enforced by the type — `source_type` is
validated against the prefix of `source_id`, so a citation cannot claim to be a document while
naming a record.

The three provenance fields answer the same three questions whatever the source is: **where** the
fact came from, **which field** carried it, and **what that field said**.

| Source | page_or_section | field_or_chunk_id | quote_or_value |
|---|---|---|---|
| Chart record | the chart section (`problems`, `labs`, `medications`) | the field (`title`, `value`, `drug`) | the value as recorded |
| Lab row read from a document | the page (`p1`) | the document (`doc:412`) | the value as read |
| Document (a "was read" claim) | the page of the patient line | the field that named the patient | the patient as printed on it |
| Guideline chunk | the section heading | the chunk id | the quoted guidance |

They were null for chart records and for document claims until late: the schema was satisfied
while three fifths of most citations said nothing, and a click on the most prominent claim on the
screen — *"Lab report X was read"* — opened page 1 with nothing highlighted. The overlay was
working; it had been given nothing to point at.

**The overlay.** Clicking a citation that names a stored document posts the page and the quote to
the module, which checks the patient's scope, checks the document belongs to this patient, audits
the view, and proxies to the agent. `pages.locate()` searches that page's **text layer** with
pypdfium2 and returns boxes normalised to 0–1, or `found: false`; `pages.render()` returns the page
as a PNG. The page renders inline with absolutely-positioned boxes sized in percentages, so they
stay aligned at any width. No model is in this path: a box is where the text is, or the page says
it is not there, and a quote on another page says so rather than guessing.

`DocumentCitation.bbox` exists and is deliberately never populated. Boxes are computed at view
time from the document's own text layer rather than stored, so a re-rendered page cannot drift out
of alignment with a coordinate recorded earlier.

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

`google/gemini-2.5-flash-lite` behind `COPILOT_VISION_MODEL`. The provider allowlist from Week 1
applies unchanged, so an unapproved vision model fails closed before any document leaves the
process, and a model that does not exist fails the same way with `OpenAIModelNotFoundError` named
in the reason.

**Why it is not a free slug any more.** OpenRouter rate-limits free models per account, not per
model. Through stage 7 three free vision slugs (Gemma 4 31B, Qwen 3.8 27B, Gemma 4 26B) all
answered `429` after backoff, so the extraction path was verified fail-closed but never
end-to-end live — the open half of metrics 11 and 12. Ten candidates were then benchmarked
through the agent's own code; the shortlist was put through real follow-ups, where
`qwen/qwen3.7-flash` refused "what medications is the patient on" and mangled source ids, and
`gemini-2.5-flash-lite` answered 6 of 6. It now reads documents live, at about $0.0009 each.
Measured over 38 reads, 2 returned nothing; that is reported as unread, never guessed.

**The retry budget is 1 on purpose.** Three backoffs are 56 seconds of a clinician waiting for a
document that is not going to arrive. One retry, then "could not be read", which is a result the
page can show and the co-pilot can say out loud.

**Document images are more sensitive than structured fields**, and the free slugs may be logged
provider-side. The default path is therefore demo-data-only, stated in `AUDIT.md`, and the paid
path is what a real deployment would use. `COPILOT_TRACE_REDACT` already exists and extends to
cover document images and extracted fields in traces.

---

## 10. Eval gate

`copilot/evals/stage2/`, **76 cases**, boolean rubrics only. Stage 1's 9 golden and 7 behavioural
cases stay untouched and keep running, which is what keeps the Week 1 baseline verifiable.
[EVAL_GATE.md](EVAL_GATE.md) is the operator's view of the same thing: where the prompts, schemas
and golden set live, how to run it, and a merge request it blocked.

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

Token and cost accounting was a declared gap in `KEY_METRICS.md` §5, and Week 2 only half closes
it. What exists is `/metrics` (`supervise_ms`, `extract_ms`, the document and handoff counters)
and a cost model in `W2_COST_LATENCY.md` computed from the request shape and checked against the
provider's credit balance — a whole 30-check walkthrough is $0.011. What does not exist is tokens
per call keyed by correlation id. The provider returns them; the service does not record them, so
the per-unit figures are computed rather than measured. That is stated as such in both documents.

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
| **The OpenEMR this runs on is not the OpenEMR it was built against** | Preflight the deploy target: `deploy/railway/preflight_module.ps1` asks it for every class and method the module calls, and calls the module's own code on it. The module guards version-dependent APIs with `method_exists` and reflection rather than assuming. **Closed on 2026-09-25** by running the same OpenEMR on Railway as locally -- see below. |

### The risk that materialised: one codebase, two OpenEMRs

This one is listed last because it was not on the list at all until it broke the deployment three
times in a row. It is the most useful thing Week 2 learned about building *on* a platform rather
than beside one.

The dev stack bind-mounts this checkout over the image, so it runs OpenEMR **8.2.0-dev** -- the
code in this repository. Railway runs the stable image with no bind mount, so it runs the image's
own OpenEMR **8.0.0**. Same module, two platforms, and every test in this repository runs against
the newer one.

| Failure | Symptom | Cause |
|---|---|---|
| Co-Pilot and Demo Data tabs blank | 500 with an empty body, tab titled "Unknown" | `PatientSessionUtil::getPid()` does not exist in 8.0.0 |
| "Generate New Docs" fails | `mkdir(): Permission denied` | The stable image's web root is read-only; the dev stack's is a host bind mount |
| Generation writes files, files nothing | `Unknown named parameter $eid` | `\Document::createDocument()` gained `$eid` after 8.0.0 |

Each was invisible locally, each produced a blank page or a generic error rather than a useful
message, and no test could have caught any of them, because the test environment *is* the other
version.

**What that changes.** Three habits, in order of how much they bought:

1. **Ask the target, not the repository.** A preflight that runs on the deploy target and calls the
   module's own code is the only check that speaks for the platform the module will actually meet.
2. **Run checks as the user the app runs as.** `railway ssh` lands as root, and the first version of
   the preflight reported the read-only web root as writable *and created it* -- which would have
   left a root-owned directory the module resolves to and cannot write into. A permission check
   under the wrong identity is worse than none: it passes.
3. **Guard the version-dependent call, do not branch on a version number.** `method_exists` and
   reflection ask the platform what it supports. A version comparison encodes a belief about what
   a number implies, and gets it wrong at the first backport.

**The limit, stated plainly.** The preflight checks that a method *exists*; it does not compare
*signatures*, which is why the third failure got through it. Signature comparison would close that
gap. The underlying difference would only be closed by building an image from this checkout --
about a day's work plus a schema migration on a live instance, which is a bigger bet than the
problem justifies while the module's own contract is `openemr >= 7.0.0`.

**Resolved, 2026-09-25.** The bet was taken after all. Railway now runs an OpenEMR image built
from this repository (`deploy/railway/build_openemr_image.sh`: upstream's release Dockerfile,
unchanged, with its source stage swapped for a `git archive` of the commit), so it runs the same
8.2.0-dev as the dev stack and the test suites. There was no live-schema migration: the new
instance was installed fresh beside the old one, with newly generated Synthea patients, and took
over the same URL by a domain rename once it passed the preflight, the co-pilot end to end and
the use-case suite. The `method_exists` and reflection guards stay, because the module's contract
is still `openemr >= 7.0.0`. The preflight stays too, run after every OpenEMR deploy. Details in
`deploy/railway/README.md`, "Current deployment".

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

**A rubric can be silenced without anyone rate-limiting it.** On 2026-09-23 `no_phi_in_logs` was
found to be scoring 74/74 against an **empty** log. `telemetry.py` configured its logger's level
only when that logger had no handlers, and the gate attaches its capture handler first, so every
event was dropped before it was written. The rubric had never run outside pytest -- where another
module imports telemetry first -- and in CI, in a fresh clone and on every direct run it was
passing vacuously. It surfaced only because under pytest it was *flaky*: a run whose `duration_ms`
happened to be 112 collided with an extracted value of 112, because the check substring-matched
against the whole JSON line rather than the fields that carry content. A second collision of the
same kind surfaced on 2026-09-27: every event carries a random `langsmith_run_id`, and about one
run in 140 it contained "112", which failed a docs-only push. Identifiers are now skipped as well:
values under keys ending in `_id`, and UUID-shaped strings.

Three things follow, and they generalise past this rubric:

- **A rubric that cannot fail is worse than one that is missing**, because it is counted. There is
  now a test asserting the gate reads a non-empty event log; nothing else in the suite could see
  this class of failure, since every other check was green throughout.
- **Flakiness was the only signal.** The instinct is to stabilise a flaky check and move on. Here
  the flakiness was the single piece of evidence that the check ran at all, and chasing it found a
  rubric that had been decorative for days.
- **Shared global state decides whether instrumentation exists.** A logger's level is process-wide,
  so an unrelated component attaching a handler first silently changed what the gate could observe.

---

## 12b. Finding: a refusal is a result, and crosses the boundary like one

The most useful bug of Week 2 was not a control that failed. It was a control that worked and
reported the opposite.

A clinician generated documents on one chart, two of them naming a different patient. The
cross-check refused every one of those, wrote nothing, and the audit log recorded each refusal.
The brief then said:

> Lab report 'copilot-demo-lab-...pdf' was read: 0 result(s) added to the chart, pending clinician
> review.

About a report belonging to someone else. Everything downstream of the refusal was correct;
everything the clinician could see said otherwise. **A safety control whose outcome is reported
wrongly is, to the person reading the screen, indistinguishable from one that did not run.** That
is the finding, and it is worth more than the fix.

### Why it happened: three silent losses at one boundary

The module is PHP and the agent is Python, and information crossed that boundary three times in
this feature. Each crossing lost something without saying so:

| Crossing | What was lost | Why it was silent |
|---|---|---|
| module -> agent, persisted documents | the `refused` reason | Pydantic drops unknown fields by default, so an un-modelled key vanishes without error |
| module -> agent, chart documents | the shape of an empty map | an empty PHP array encodes as `[]`, not `{}`, so an intake form with nothing readable rejected the whole chart |
| module -> OpenEMR, refusal note | the write itself | `Document::createDocument()` takes its data **by reference**, so a cast expression is a runtime error, not a type error |

None of the three produced a wrong value. Two produced no value and one produced a 500, and in
every case the calling code carried on with a plausible-looking result. The happy path was typed,
schema-validated and covered by cases; the refusal path travelled as an ad-hoc dictionary key.

### What this changes about how the seams are built

1. **A refusal is modelled as explicitly as an acceptance.** `PersistedRef.refused` is a declared
   field with a declared type. Anything a control decides is part of the contract, not a note
   attached to it.
2. **A refusal is a terminal state, not a pending one.** Left as "unprocessed", a refused document
   was offered back to the extractor on every open: read again, refused again, reported again --
   six documents on one chart meant six vision calls a visit, for ever. The refusal is now recorded
   beside the document, where a human can also see it.
3. **The gate covers what the system declines to do.** It already covered what it does. Cases now
   assert the refusal reaches the clinician, and a use case asserts a refused document is not read
   a second time.
4. **Boundary shapes are asserted, not assumed.** The empty-map case is the kind of thing that only
   appears when a real document happens to contain nothing readable -- which is precisely the
   degraded input this system exists to handle honestly.

### The general rule this leaves behind

Every control in this design has two outcomes, and only one of them was ever really built. When a
check passes, the value flows on through typed structures that are validated at each step. When it
fails, the *absence* flows on -- and absence is exactly what a schema with permissive defaults, a
JSON encoder with ambiguous empties, and a caller that tolerates missing keys will quietly convert
into "nothing to report". **Build the refusal path with the same rigour as the acceptance path, or
the system will be safe and look unsafe -- or worse, be safe and look fine while saying nothing at
all.**

### The same pattern, found again on 2026-09-27

Asked "what is the recommendation" twice in a row, the co-pilot gave two different answers. The
supervisor routed both to the guideline corpus. The second time the model searched, and three
guideline passages were shown. The first time it made no tool call and answered with a boundary
statement plus "no specific guidelines were found in the search results", about a search that
never ran, and the turn was reported **Complete**.

The prompt asked for the search but nothing enforced it. The two passes that catch "answered
without looking" both stand aside for a boundary statement, and a boundary is exactly what the
model wrote. The boundary and "missing" text is not a claim, so the verifier never checked it, and
a turn with nothing kept and nothing removed counted as complete. Every gate case on the evidence
path had scripted a model that searched, so the path where a refusal meets an evidence question had
no case.

The fix is grounding rule 13 (`copilot/evals/stage1/GROUNDING_RULES.md`). An evidence turn's first
round is forced to call a tool. A second forced pass follows if no search ran, even after a
boundary. If the search still never ran, the answer shows no guidance, says "No guideline search ran
for this question", and is `partial`. Gate cases S11 (made to search) and S12 (never searches) were
written first and failed on the unfixed code. The gate's text checks now read the boundary as well
as the claims.

---

## 13. Implementation sequence

Thin vertical slice first, gate early, breadth last. Each stage ends green.

| # | Stage | Ends when |
|---|---|---|
| 0 | **Done.** Co-Pilot tab in the patient record via `PatientMenuEvent`; scope enforced from session `pid` | Out-of-panel patient is refused and audited from the new entry point (`usecases/test_uc_patient_tab.py`) |
| 1 | **Done.** `documents/schemas.py`; `Citation` gains the v2 fields; verifier learns `document:` and `guideline:` | Week 1 citations still resolve; unsupported fields cannot validate as supported (`test_document_schemas.py`, `test_verify.py`) |
| 2 | **Done.** `DocumentWriter.php`; `api.php` actions `attach` and `persist_extraction` | An extracted lab reads back as a FHIR Observation (`status: preliminary`) and is selectable in Lab Overview (`test_uc_document_writer.py`) |
| 3 | **Built.** `documents/extract.py`, `POST /documents/extract`, `attach` extracts then persists; `/ready` checks the vision model | Proven with a scripted model (`test_extract.py`) and fail-closed live. A successful live extraction is pending a vision model with quota: OpenRouter's free tier is rate-limited per account, and the build exhausted it (§9) |
| 4 | **Done.** `evals/stage2/gate.py`, 76 cases, `baseline.json`, `hooks/pre-push`, and the `eval gate` job in CI; `test_gate.py` removes four guards in turn | An injected regression blocks a push *and* a merge — demonstrated in MR !2, where the pipeline failed and the merge was blocked |
| 5 | **Done.** `IntakeForm` extraction; sidecar document under Medical Record; six intake cases in the gate | Intake facts cited to the form, never merged into `lists` (`test_uc_document_intake.py` asserts the row count is unchanged) |
| 6 | **Done.** `guidelines/retrieve.py`, 20-chunk corpus, `search_guidelines` tool, `evidence` section; six retrieval cases in the gate (62) | Guideline evidence cited separately, barred from patient-fact claims (`test_guidelines.py`, G01–G06) |
| 7 | **Done.** `supervisor.py` (LangGraph, interrupt while the module persists), `/session/{sid}/supervise` and `/resume`, module `supervise` action, patient tab runs it on open | Routing reconstructable from logs (`test_supervisor.py`, `test_uc_supervise.py`); no-documents path degrades to Week 1 |
| 8 | **Done.** 76 cases across extraction, intake, citation, retrieval, refusal, brief, missing data and the supervisor graph, including the routing decisions added later; baseline recorded | All five rubrics at 100 % |
| 9 | **Done.** `documents/pages.py`, `POST /documents/page`, module `page` action, chip click opens the page with the quote boxed; lab rows read from a document carry `document_id` and `page` | A claim opens its page with the quote highlighted (`test_pages.py`, `test_uc_document_page.py`) |
| 10 | **Docs done.** README Week 2 section, `KEY_METRICS.md` Week 2 section, `W2_COST_LATENCY.md`, `USER.md` Week 2 use cases, collection requests 11–13, and the three artifacts refreshed. Railway deploy waits on the publish gate; the GitLab CI pipeline is parked, not wired | Graders can run the Week 2 flow without guessing; the deployed app is the remaining item |

Stage 4 is deliberately fourth. The eval gate is the Week 2 hard gate, and building it against a
working slice means every later stage lands against a gate that already works.

---

## 14. Validation tooling: the Demo Data tab

**Not part of the product.** It exists so the Week 2 ingestion flow can be exercised without
hunting for a real PDF, and it is removed before production.

**The decision that shaped it.** The first design generated documents straight into the chart,
which was wrong twice over. It would have skipped the step the requirement actually names --
*accepts a file* -- so the flow being demonstrated would not have been the flow being graded. And
because it created chart documents, it also needed to delete them, which put a delete path against
a clinical record inside a module that writes to charts.

Writing files to a folder instead removes both problems. The helper never touches the database on
the way in. A lab drops a report somewhere, a human uploads it, and the ingestion path that runs is
the ordinary one. It also let the whole repeatability design go: every generation is a new document
with a new accession and date, so a second run produces a truthful "what changed" with nothing
reset first, which is what a real chart does anyway.

| Decision | Choice | Why |
|---|---|---|
| Where documents are generated | A file under the web root's `demo/generated/` where that is writable, otherwise `sites/<site>/copilot-demo/generated/` -- **and** filed in the chart unread through the same `storeDocument` an upload uses | Generating a file the clinician then has to upload by hand is a step that exists only for the demo, and it was the part that felt wrong in use. The file is still written, still downloadable, and the by-hand upload still works -- but the default path is the one a clinician would actually experience: the document is simply there, and the co-pilot reads it on its next run |
| Who writes the PDF | The module, in PHP, with a deliberately primitive writer | mPDF and dompdf are both available, but they embed subset fonts whose text layer extracts unreliably. Click-to-source depends on that text layer, so the generator uses the same Courier-and-text-operators shape the eval fixtures use, which is known to extract cleanly |
| Patient identity on the document | Read from the chart being viewed | The document's own patient reference then agrees with the chart it is filed in. `patient_ref` is extracted for a cross-check that is **not yet enforced**; matching names keeps the demo honest rather than hiding that |
| Values | Fixed per variant, only identifiers and dates vary | A randomised potassium would some runs fail to reach the rule engine, and a demo that behaves differently each time teaches nothing |
| Gate | `COPILOT_DEMO_TOOLS`, default false in code | A deployment that sets nothing never exposes it. The tab is not registered *and* the actions refuse, so a stale browser tab cannot reach a live endpoint |
| Purge | Files, the documents uploaded from them, and the lab rows those produced | Deleting only the document would leave results whose citations open a page that no longer exists -- worse than deleting nothing. Scoped to its own `copilot-demo-` filenames |
| Removal | One file, one registration block, one action block | `src/DemoDocuments.php`, the block in `Bootstrap::addPatientTab`, the `demo_*` case in `api.php`, `public/demo.php` |

A co-pilot tab already open would otherwise sit on a chart that has since gained a document, so
`patient.php` exposes `window.cpaRereadDocuments()` and the Demo Data tab calls it when one is
open. That is the whole of the coupling between the two, and it goes when the demo tooling goes.

**As built.** `DemoDocuments::generate()` writes a two-page lab report and a one-page intake form
named `copilot-demo-<kind>-<timestamp>.pdf`. The lab report has three results on page 1 and two on
page 2, so per-page citations are exercised. The intake form carries a line instructing any
automated reader to ignore its allergies section, which the extraction disregards. `demo_file`
streams a generated file for download, matching the requested name against the listing rather than
treating it as a path. Every action is audited (`copilot-demo-generated`, `copilot-demo-downloaded`,
`copilot-demo-purged`), hospitalist-only, and scope-checked like every other patient action.

**Verified live, end to end**, on pid 1 (hypertension, chronic kidney disease, on lisinopril and
naproxen -- a chart where a potassium of 5.4 is a real finding rather than merely a red number):
generate, upload through the chart, one unread document found, read in 20.9 s with five results
filed pending review, "what changed" citing `doc:2183`, a follow-up answered from the newly
ingested row, then purge removing 2 files, 1 document and 5 results.

### The patient cross-check

A document is filed under a patient by whoever uploaded it, and people misfile things. The name
printed on the report is the document's own claim about whose results these are, so it is checked
against the chart before anything it says becomes chart data.

`patient_ref` had been extracted since stage 1 and described as being "for the cross-check", but
nothing compared it to anything -- a gap found by asking what would happen if the demo generator
produced a document for the wrong patient. `DocumentWriter::patientRefMismatch()` now closes it, on
both write paths: the single-document `attach` and the supervisor's persist step.

A mismatch is **refused, not reconciled**. Filing another patient's potassium into this chart is
the worst outcome this feature can produce, and there is no reading of a mismatch that makes
persisting safe. The document stays stored for a human to look at, nothing reaches the chart, and
the brief says so -- because a document that silently produced nothing looks exactly like one that
was never there. It **fails closed on an unreadable name** for the same reason: a report whose
patient could not be read is not evidence that it belongs here.

Matching is forgiving about form and strict about content. Case, punctuation and word order are
ignored, so "Doe, Jane" matches "Jane Doe"; but every name part in the chart must appear, so an
initial where the chart holds a full given name is not a match, because "J. Doe" does not
distinguish Jane from John. The Demo Data tab's `wrong_patient` variant generates a report naming
someone else so the refusal can be demonstrated, and a live case asserts both halves: the
mismatched report is stored and never filed, the matching one is filed.

A document that yields nothing at all -- a scan with no text, the ordinary degraded case -- is
told apart from one that names someone else. Both fail closed and neither is filed, but "the
patient name could not be read" on a wholly blank page reads as a name-matching problem on a real
report, which is alarming and untrue; it now says nothing could be read. The `unreadable` demo
variant blanks both documents of a pair for the same reason: blanking only the lab produced a run
where the report could not be read while the form beside it read perfectly, which looks like a
fault rather than the case the variant exists to show.

On screen, a line for a document that did not reach the chart is coloured rather than left to read
like every other line: red for a refusal (it belongs to someone else, or could not be confirmed to
belong here) and amber for one the model could not read, each with a short NOT FILED or NOT READ
tag. The marking is keyed on what the module and the graph reported -- `persisted[].refused` and
`failed[]` -- not on the wording of the sentence, which is ours and stable but one rewrite away
from silently marking nothing.

A refusal is recorded beside the document, as a small JSON note a human can see in the Documents
tab. Without it a refused document stayed *pending*: the extractor was offered it again on every
open, the vision model read it again, and it appeared in "what changed" again. Reported from the
local install as six documents on one chart, three refused, all six re-read every visit.

Two bugs were in the way of that working, both worth naming. `PersistedRef` had no `refused`
field, and Pydantic drops unknown fields in silence -- so the refusal never reached the graph and
the brief described a report belonging to someone else as "was read: 0 result(s) added to the
chart, pending clinician review". And `Document::createDocument()` takes its data **by reference**,
so passing a cast expression failed at runtime and turned every refusal into a 500.

One consequence worth recording: this broke two live tests that had been uploading the committed
eval fixture, which names a fictional patient, to a real chart. They were misfiling a document on
every run and passing anyway. They now build a report naming the patient they file it under
(`usecases/labpdf.py`), which also means the extraction case genuinely exercises the persist path
instead of skipping.

**When the clinician opens another chart.** Both tabs render with the open patient baked in and
nothing tells them when that changes. The Co-Pilot tab is a reader, so it says plainly that what
is shown belongs to a patient no longer in view. The Demo Data tab **writes** -- generating files
documents into a chart, purging deletes from one -- so a banner is not enough: `demo_generate` and
`demo_purge` refuse outright unless the patient is still the one in view, and the buttons disable
themselves. Demonstrated before the check existed: a stale tab wrote two documents into a chart
nobody was looking at. Panel scope does not catch this, because the stale patient is in the panel
too.

Finding that required reading the active patient the way OpenEMR actually stores it. `api.php` was
reading the raw `$_SESSION['pid']` superglobal, which is empty -- the active patient lives behind
the session wrapper -- so it had been 0 on every request, and the encounter-attachment check
beside it (`$sessionPid === $pid`) had quietly never matched. It now reads through
`PatientSessionUtil::getPid()`, as `patient.php` always did.

**What it does not prove.** Generated documents have a clean text layer, so click-to-source always
resolves. A real scan would not, and there is no OCR. The unreadable variant exists so that path is
shown rather than implied away.
