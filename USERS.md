# Clinical Co-Pilot: Target User and Use Cases

**Status:** source of truth for Stage 5. Every capability in `ARCHITECTURE.md` must cite a use case ID from this document (`UC-1` … `UC-6`). Requirements cite `REQ-*`. Data and security constraints cite [AUDIT.md](AUDIT.md) finding IDs (`D*`, `P*`, `S*`, `C*`).

**Date:** 2026-09-15.

---

## 1. Target user

### 1.1 Who

**A day-shift hospitalist rounding on twelve admitted patients before noon.**

| Attribute | Definition |
|---|---|
| Role | Attending physician, internal medicine, adult inpatient ward, community hospital. Non-teaching service, so there are no residents to pre-round for them. |
| Shift | 07:00–19:00, on a block schedule, often a stretch of days in a row. Day one of a block means inheriting patients they have never met. |
| Census | **12 patients**: about 9 carried over from yesterday and about 3 new admissions taken overnight by the nocturnist. |
| Morning goal | See and examine all 12 and decide each patient's plan, get the likely discharges out **before noon**, then write notes and take new admissions in the afternoon. |
| Tools today | The EHR (chart review, flowsheets, results, medication lists), a written or verbal sign-out from the night team, a paper or printed rounding list, pages and secure chat from nursing. |
| Devices | A workstation (primary) and a hospital phone between rooms (secondary). |

### 1.2 What they need from an agent, and what they will not tolerate

| Tolerates / wants | Will not tolerate |
|---|---|
| "Not recorded" or "I can't tell from the chart" | A number, medication or result that isn't in the chart (fabrication) |
| Short, scannable output with the important items first | Paragraphs of prose to read for 12 patients |
| Every claim linked to its source and time | Unsourced summaries they would have to re-verify anyway |
| Being told what changed since yesterday | A re-summary of the whole 20-year history every morning |
| A read-only assistant | Anything that places orders, writes to the chart or messages staff on its own |
| Waiting a few seconds for a considered answer | Waiting on every click; slowness at 07:00 means they'll go back to the chart |

### 1.3 Who this is *not* for (and why they are excluded)

- **ED resident on overnight intake:** needs quick assessment of undifferentiated patients with little history. A different problem shape and different speed expectations.
- **Primary care physician:** schedule-driven outpatient visits with a longitudinal focus. The data fits, but the workflow is different.
- **Nurses, case managers, patients:** different permissions, different questions, and patient-facing output raises separate safety and regulatory issues.

Choosing the hospitalist means this document optimizes for **change since last review, prioritization across a census, and answers under time pressure**, not population analytics or visit preparation.

### 1.4 Working assumptions (to be validated)

The workflow figures below are **assumptions** drawn from common descriptions of hospitalist practice. They are not measured here. Validate them with at least one practicing hospitalist before Stage 5 locks targets (see §7).

- Pre-round chart review takes about 4–6 minutes per patient, roughly 50–70 minutes for 12.
- Interdisciplinary rounds with nursing and case management happen mid-morning.
- A new admission from overnight gets the longest review of the morning.
- Most chart-review time goes to navigating between screens (vitals, labs, medications, notes), not to thinking.

---

## 2. Workflow: one morning

| Time | What the hospitalist is doing | Pain today | Where the agent enters |
|---|---|---|---|
| 06:45 | Arrives and takes sign-out from the nocturnist (verbal plus a written sheet): who was admitted, who had events overnight | Sign-out is compressed; details ("what was the potassium?") live in the chart | — |
| **06:55** | **The 30 seconds before:** sits at a workstation with coffee and the sign-out sheet. Knows *that* bed 7 had a fever and there are three new admits, but not the details. Opens the rounding list. | Twelve charts, each needing 6–8 screens | **Opens the co-pilot: the morning brief for all 12 is already waiting (UC-1)** |
| 07:00–07:45 | Pre-rounds: reviews every patient's overnight changes and writes a to-do list | 50–70 min of clicking; changes get missed when a result is on page 3 | UC-1 overnight change brief · UC-2 new-admission catch-up |
| 07:45 | Decides rounding order: unstable patients first, likely discharges early, new admits | Done from memory plus sign-out; easy to under-prioritize a quiet deterioration | UC-3 rounding order with reasons |
| 08:00–11:30 | Bedside rounds, interdisciplinary rounds, family calls, orders, pages | Ad hoc questions mean walking back to the workstation and re-opening charts | UC-4 bedside follow-up questions · UC-5 medication discrepancy check |
| 10:30–11:45 | Discharge push for 2–4 patients: reconcile medications, check pending results, arrange follow-up | Pending items get discovered late, delaying discharge past noon | UC-6 discharge-readiness check |
| Afternoon | Notes, new admissions, sign-out to the night team | (Out of scope for this document) | — |

**What they do with the output:** the agent's output becomes the hospitalist's **to-do list and rounding order**, and the questions they ask at the bedside. Every action (orders, notes, calls) still happens in the EHR, by the clinician.

---

## 3. Use cases

Each use case covers the moment, the question asked, what the agent returns and what the user does with it, the data needed, success criteria, **why an agent is the right shape**, what the agent must not do, and how well this repo's data supports it today.

MVP priority: **P0** = build first · **P1** = build if P0 meets its targets · **P2** = design for, may stay a talking point.

---

### UC-1: Overnight change brief across the rounding list (P0)

**Moment:** 06:55–07:45, pre-rounds at the workstation.

**The ask:** "What changed for each of my 12 patients since yesterday's review, and what needs my attention?"

**The agent returns** one card per patient, in list order, each **at most 8 lines**:
1. **Flags first:** new abnormal-trending vitals, new results since the last review, medications started or stopped, new problems. Each flag has a one-line reason.
2. **Changes since the last review:** time-bounded to "since 07:00 yesterday", or since the hospitalist's last session.
3. **Explicitly nothing:** "No new labs since 07:00 yesterday" or "Vitals not recorded overnight". Silence is never left to be interpreted.
4. Every item links to its source resource and timestamp.

**The user then** scans all 12 cards in about 10 minutes instead of 50–70, writes the to-do list, and opens the full chart only for flagged patients.

**Data needed:** encounters (current admission), vital-sign observations with timestamps, lab results with collection times, medication requests with start and end dates, new or changed problems, and overnight nursing or sign-out notes.

**Success criteria:**
- The brief is ready **before 06:55** (pre-computed; see REQ-LAT-1).
- Every flag cites a source and time.
- 0 fabricated values in evaluation.
- Recall ≥ 95% on seeded "overnight change" test cases.
- The hospitalist can say "nothing changed" for a stable patient in under 15 seconds.

**Why an agent (and not a dashboard, sorted list or better chart view):**
- **The meaning of "changed" depends on each patient.** A potassium of 5.1 matters for a patient on spironolactone with kidney injury and is noise for someone else. A dashboard shows the same columns for everyone. The agent pulls together vitals, labs, medications and problems for each patient and writes a one-line *reason* for each flag.
- **Messy data needs judgment.** In this system, medication "active" flags are wrong 79% of the time (AUDIT D1), problems repeat (D3), and vitals are sparse (D4). A dashboard shows these errors faithfully; the agent's tools correct them and say what's missing ("BP not recorded").
- **The brief is where the conversation starts.** From any card the hospitalist can ask "show me the trend" or "why was that flagged?" without leaving the flow (UC-4). A static view ends at display.
- **Honest limit:** a trend graph is still the better way to *see* a vitals trend, so the agent should link to one, not describe the graph in words. The agent's value is choosing *which* of 12 patients' hundreds of data points deserve attention, and saying why.

**Must not:** recommend treatment ("start antibiotics"), suppress an item without saying so, or present an old value as overnight data.

**Data support in this repo:**
- **Partial.** Lab history is real (16,783 results, 651 collection days, 2016-10-04..2026-08-26, dated from the report in FHIR), and there are 87 admission-type encounters across 34 patients.
- **Gap:** no one is admitted "today"; there are no overnight vitals series (one vitals form per patient), no notes of any kind, and no results in the last 30 days.
- **Needs** the inpatient data overlay described in §5.

**Audit links:** D1, D3, D4, D7 (normalization) · P2–P4 (pre-computation; no raw bundles to the LLM) · S3 (scope to the rounding list).

---

### UC-2: New admission catch-up: "who is this patient?" (P0)

**Moment:** 07:00–07:30, first look at the 3 overnight admissions (and every patient on day one of a block).

**The ask:** "Catch me up on bed 12. I've never met her."

**The agent returns** a structured pre-admission picture in about 12 lines:
- **Active chronic conditions**, as disorders only, de-duplicated (D3).
- **Social context**, kept as its own short line (employment, isolation, stress), not mixed into diagnoses.
- **Home medications with verified status** (D1/D2).
- **Allergies**, or "none recorded" (D7).
- **Recent hospital use:** "3 ED visits and 1 admission (7 days) in the past 2 years".
- **Relevant baselines:** last known creatinine or eGFR, and last A1c, with dates.
- **The reason for this admission** and what's pending.

**The user then** starts the bedside encounter already knowing the patient's baseline, and asks targeted follow-ups (UC-4).

**Data needed:** problems, medications (both stores), allergies, encounter history by type, baseline labs (BMP, eGFR, glucose, and so on).

**Success criteria:**
- Generated in ≤ 20 s on demand, or pre-computed with UC-1.
- Chronic-condition list precision ≥ 90% against a clinician-labeled reference for evaluation patients.
- Social findings never listed as diagnoses.
- Baseline values always dated.

**Why an agent:**
- **Twenty years of history compressed into what matters for this admission.** Synthea histories run up to 279 encounters and 282 problem entries per patient (AUDIT §2.1). A chart view shows all of it; a sorted list still makes the physician scan 282 rows, 70% of which are social findings.
- **Relevance depends on the reason for admission.** Baseline creatinine matters for an admission with kidney injury; prenatal history matters for an obstetric admission. The agent chooses the relevant slice for the admission; a fixed summary template can't.
- **It is where the conversation starts.** "Has she been admitted for this before?" is the natural next question, and it's asked in place.

**Must not:** infer diagnoses not coded in the chart, or restate social findings as clinical problems.

**Data support in this repo:** **Strong.** Lifetime problems (100% SNOMED coded), medications (100% RxNorm), allergies, 2,128 encounters including 87 hospital- or ED-type admissions, and dated lab baselines. This is the use case best supported by data today.

**Audit links:** D1, D2, D3, D6, D7, D8 · P2, P4.

---

### UC-3: Rounding order with reasons (P1)

**Moment:** 07:40–07:50, after pre-rounds and before walking.

**The ask:** "Who should I see first?"

**The agent returns** the 12 patients grouped as **See first** (possible instability), **Likely discharge today** (see early to start paperwork) and **Routine**. Each has a **one-line reason tied to data**, e.g. "HR trending 88→112 overnight; new lactate pending", and each placement can be overridden.

**The user then** accepts or reorders the list and starts rounds. The agent never reorders silently later.

**Data needed:** UC-1 output, plus discharge signals (stable vitals, active medications changed to oral, pending results) and the sign-out notes the hospitalist typed or pasted in.

**Success criteria:**
- Every group placement has a data-cited reason.
- On seeded scenarios, every patient seeded as "deteriorating" appears in *See first*.
- The hospitalist overrides the order ≤ 3 of 12 times in pilot feedback.

**Why an agent:**
- **A fixed acuity score can't use the sign-out.** An early-warning score (NEWS2-style) sorts on vitals alone. The hospitalist's real ordering also depends on the sign-out ("family meeting at 10", "surgery wants to see her first") and on discharge readiness. The agent combines the structured signals with free-text context the user provides, and explains the result.
- **Explanation is the product.** A ranked list without reasons gets ignored, while "see first because …" can be checked in seconds.
- **Honest limit:** if a validated early-warning score is available, the agent should *show it*, not replace it. The agent adds context and reasons around it. Clinical prioritization remains the physician's decision.

**Must not:** present the ordering as a triage decision, hide any patient, or make predictive claims ("will deteriorate").

**Data support in this repo:** **Gap.** It needs the current-admission overlay (§5) for overnight trends and discharge signals.

**Audit links:** D4 · S3 · P3.

---

### UC-4: Bedside follow-up questions (P0)

**Moment:** 08:00–11:30, between rooms, on the phone or a workstation, often while standing in the hallway.

**The ask** (examples, deliberately unpredictable):
- "When was her last potassium, and what's the trend over the last three draws?"
- "Was she on anticoagulation before admission?"
- "Has he had a CT in the last year?"
- "What's his baseline creatinine?"

**The agent returns** a direct answer in 1–3 sentences, the values with dates, and links to the sources. When the chart doesn't hold the answer, it says **"not recorded in this chart"**.

**The user then** acts at the bedside (examines, adjusts the plan, talks to the patient) without walking back to open the chart.

**Data needed:** the patient-scoped FHIR read tools (labs, medications, problems, encounters, immunizations, allergies), restricted to patients on today's list.

**Success criteria:**
- Median answer ≤ 5 s, p95 ≤ 10 s (REQ-LAT-2).
- ≥ 95% factual accuracy on the evaluation question set.
- 100% of numeric answers carry a date and a source.
- "Not recorded" returned rather than a guess on 100% of unanswerable evaluation questions.

**Why an agent:**
- **The questions are unpredictable.** No dashboard has a tile for "anticoagulation before admission". Answering it means searching medication history against a class (warfarin, apixaban, rivaroxaban …) filtered by date, which is natural-language intent translated into a filtered query. That's exactly what a tool-calling agent does.
- **Chart navigation is the cost.** The information exists, but reaching it takes several screens per question. Asked 10–20 times a morning, that adds up to real time.
- **Context carries between questions.** "And the one before that?" works because the conversation remembers the patient and the test.

**Must not:** answer about a patient not on the rounding list, give dosing recommendations, or answer from general medical knowledge presented as if it were chart data.

**Data support in this repo:** **Strong for history and labs** (100% coded labs with units; dated reports). **Gap for overnight or current-admission questions** until §5 is in place.

**Audit links:** S3 (scope), P1–P3 (latency), D5 (no reference ranges, so never label "abnormal" without a cited reference), D7.

---

### UC-5: Medication discrepancy check (P1)

**Moment:** 08:00–11:30 at the bedside, and again during the discharge push.

**The ask:** "Any medication problems I should know about for bed 4?"

**The agent returns** a short list of **discrepancies, each explained**:
- **Stale "active" flags:** flagged active but ended (e.g. "ended 2019-03-02").
- **Duplicates across medication lists:** the same drug in `prescriptions` and `lists`, or two drugs of the same class.
- **Home medications not continued** in the current admission.
- **Medications with no start date or route.**

Each item has its source and dates. It gives **no recommendation to start, stop or change** anything.

**The user then** confirms with the patient or pharmacy and reconciles in the EHR.

**Data needed:** `MedicationRequest` (FHIR), `lists` medications (REST), and dates. Where available, the current-admission medication orders (§5).

**Success criteria:**
- 100% of seeded stale-active and duplicate cases are detected.
- 0 false "discontinued" claims on medications that are actually current.
- Every discrepancy names both conflicting sources.

**Why an agent:**
- **The contradiction *is* the finding.** This system stores medications twice (299 of 306 prescriptions duplicated, D2) with status flags that contradict the dates (243 of 306, D1). A list view shows both copies as "active". Finding and explaining a discrepancy means reasoning across two sources with conflicting fields.
- **Explanation drives action.** "Metoprolol appears twice: once from the 2021 prescription (ended 2022-01-10) and once in the medication list with no end date" gives the physician the exact thing to ask the patient.
- **Honest limit:** interaction checking is better done by the EHR's rule-based drug-interaction engine. The agent should not claim to check interactions.

**Must not:** recommend medication changes, perform interaction checking, or treat the `active` flag as truth.

**Data support in this repo:** **Strong for the core finding.** The real data already contains the D1 and D2 discrepancies. "Home medications not continued" needs the §5 overlay (inpatient orders).

**Audit links:** D1, D2 · C4c (minimum necessary: send only the medication fields).

---

### UC-6: Discharge-readiness check (P2)

**Moment:** 10:30–11:45, for the 2–4 patients flagged "Likely discharge today".

**The ask:** "Is bed 9 ready to go? What's outstanding?"

**The agent returns** a checklist taken from the chart:
- Pending or unresulted labs and imaging ordered this admission.
- Medication changes made during the stay that the patient needs to know about.
- Last vitals with their time.
- Follow-up appointments on file, or "none on file".

Each item is cited. **The discharge decision is not made by the agent.**

**The user then** clears the outstanding items, or holds the discharge and tells case management.

**Data needed:** procedure orders with report status for this encounter, medication changes during the admission, vitals, and appointments.

**Success criteria:**
- Every seeded pending order is surfaced.
- Checklist generated in ≤ 20 s.
- No discharge-appropriateness claims.

**Why an agent:**
- **Discharge blockers are scattered across order status, medications and scheduling.** A dashboard would need an integration built for each. The agent assembles them per patient from the same tools used in UC-1 and UC-5, so there are no new screens.
- **Honest limit:** hospitals that already have a discharge milestone tracker should keep it, and the agent should read from it. This use case is P2 because its value depends on an admission data model this repo lacks, and OpenEMR has no calendar or follow-up data (0 appointments).

**Must not:** declare a patient ready or not ready for discharge, or schedule follow-ups.

**Data support in this repo:** **Gap.** Orders link to encounters (7,391 of 7,391), but there is no current admission, no appointments and no pending-result status for today.

**Audit links:** D8 · P3.

---

## 4. Agent boundaries (all use cases)

These are **requirements**, not preferences. Stage 5 must enforce them in code and cover them in evaluations.

| ID | The agent will not… | Why |
|---|---|---|
| NG-1 | Place orders, write to the chart, send messages or page anyone | Read-only v1 keeps every clinical action with the clinician (and avoids the unaudited write path in AUDIT C1b) |
| NG-2 | Recommend diagnoses, treatments, doses or discharge decisions | It surfaces chart facts and flags for clinician judgment; it isn't clinical decision support |
| NG-3 | Answer about patients outside the hospitalist's rounding list | Minimum necessary (§164.502(b)); user scopes are otherwise population-wide (AUDIT S3) |
| NG-4 | State a clinical value without a source and date | Trust requires checkable claims; unsourced summaries get re-verified or ignored |
| NG-5 | Fill gaps with general medical knowledge presented as chart data | It says "not recorded in this chart" (AUDIT D5, D7) |
| NG-6 | Push unsolicited alerts | Alert fatigue; the hospitalist pulls information when ready |
| NG-7 | Label a lab "abnormal" without a cited reference range | The data has no ranges or abnormal flags (AUDIT D5) |

---

## 5. Data readiness for this user

The dataset was measured on 2026-09-15 against the 50-patient Synthea import. OpenEMR is an ambulatory-first EHR and Synthea generates lifetime histories, so the data fits *historical* questions well and *current-admission* questions poorly.

| Needed by the hospitalist | In this repo today | Supports |
|---|---|---|
| Patient history (problems, medications, allergies) | 1,750 problems (100% SNOMED), 306 prescriptions (100% RxNorm), 59 allergies across 7 patients | UC-2, UC-4, UC-5 ✅ |
| Prior hospital use | 87 admission-type encounters (49 ED admissions, 12 hospital admissions, 9 surgical, 9 obstetric …) across 34 patients; 36 in the last 2 years; hospital admissions average 7.6 days | UC-2 ✅ |
| Lab history and baselines | 16,783 results, 111 distinct tests (e.g. BMP components ×381), collection dates 2016-10-04..2026-08-26 on 651 days; FHIR `effectiveDateTime` comes from the report date. No reference ranges or abnormal flags (D5) | UC-2, UC-4 ✅ (history) |
| **A current admission ("today's 12")** | None. All 2,128 encounters are class `AMB`; no calendar events, patient tracker, care teams or assigned providers | UC-1, UC-3, UC-6 ❌ |
| **Overnight vitals series** | One vitals form per patient; BP, weight and SpO₂ empty for all 50 (D4); none in the last 7 days | UC-1, UC-3 ❌ |
| **Recent results (last 24 h)** | None in the last 30 days | UC-1, UC-4 (current) ❌ |
| **Nursing, progress, consult and sign-out notes** | None (`pnotes`, `form_soap`, `form_clinical_notes`, `documents` all 0) | UC-1, UC-3 ❌ |
| Inpatient medication orders or administration | None (OpenEMR has no medication administration record) | UC-5 (home vs inpatient) ❌ |

**Requirement for Stage 5 (REQ-DATA-1):** build a **current-admission overlay** for the demo rounding list. It needs 12 patients with an open inpatient encounter, overnight vitals and lab results timestamped relative to "today", medication changes, and short overnight nursing and sign-out notes.
- **Every scripted patient maps to a UC-1 flag** (deterioration, new result, medication change, stable), so evaluations have known answers.
- **Load it through the OpenEMR API or service layer, never raw SQL**, so UUIDs, events and audit logging apply (AUDIT C1b).
- **Record in `ARCHITECTURE.md`** how the overlay is produced and how it is reset for evaluations (D9).

**Why OpenEMR for an inpatient user:** OpenEMR is the platform provided for this project. The agent reads through FHIR R4 (US Core) over SMART/OAuth2, the same interface inpatient EHRs expose, so the tool layer and evaluations carry over. The overlay stands in for inpatient data OpenEMR doesn't produce.

---

## 6. Cross-cutting requirements derived from these use cases

| ID | Requirement | Derived from | Constraint from AUDIT |
|---|---|---|---|
| REQ-LAT-1 | UC-1 briefs (and UC-2 for new admits) are **pre-computed before 06:55** for the whole rounding list; if the chart changes after that, the brief is refreshed on open | UC-1, UC-2 | P1–P3: ≈11.4 s per patient for sequential FHIR reads, ≈2.3 min for 12 |
| REQ-LAT-2 | Interactive answers: **median ≤ 5 s, p95 ≤ 10 s**, measured from question to first complete answer | UC-4, UC-5 | P1 (1–2.7 s per call), so parallel filtered reads and a per-session cache are required |
| REQ-SCOPE-1 | The agent can only access patients on the authenticated hospitalist's rounding list for today. **The agent's tool layer is the only enforcement point** — see below | NG-3, all UCs | S3, C4c |
| REQ-CITE-1 | Every clinical value in output carries source resource type, ID and timestamp | NG-4, all UCs | — |
| REQ-NORM-1 | Tools normalize before the LLM sees data: medication status from dates, cross-store de-duplication, SNOMED semantic-tag separation, dated vitals, "none recorded" semantics | UC-1, UC-2, UC-5 | D1, D2, D3, D4, D7 |
| REQ-MIN-1 | Tools return compact, field-limited summaries, never raw FHIR bundles | UC-1, UC-2, UC-4 | P4 (a 475 KB Condition bundle), C4c |
| REQ-RO-1 | Read-only: no write tools in v1 | NG-1 | C1b |
| REQ-AUDIT-1 | Every agent data access is attributable to the agent client, the hospitalist and the originating question | All UCs | C1c |
| REQ-FMT-1 | Patient cards ≤ 8 lines with flags first; bedside answers of 1–3 sentences; both readable on a phone | UC-1, UC-4 | — |
| REQ-DATA-1 | A current-admission overlay for the 12-patient demo list, loaded through the API or services and resettable for evaluations | UC-1, UC-3, UC-6 | C1b, D9 |
| REQ-PHI-1 | With real PHI, the model endpoint and tracing must be under a BAA or receive de-identified data | All UCs | C4a, C4b |

### OpenEMR does not enforce per-provider scoping (measured 2026-09-15)

Assigning each patient a provider does **not** restrict anyone. OpenEMR's authorization is role-based (gacl: "may this role read demographics?"), never patient-based ("which patients are mine?"), and `providerID` is a demographic field.

Verified on the Railway deployment with the panel split 25/25 between `doctor1` and `doctor2`:

| Signed in as | FHIR `/Patient` | REST `/api/patient` | Assigned in the database |
|---|---:|---:|---:|
| `admin` | 50 | 50 | — |
| `doctor1` | **50** | **50** | 25 |

The only built-in restrictions are facility-based (`restrict_user_facility`, facility/warehouse permissions), and every provider here shares one facility. OpenEMR's patient-filter events (`PatientFinderFilterEvent`, `AppointmentsFilterEvent`, demographics view/update) can hide patients in the **UI**, but no equivalent hook exists in `apis/` or `src/Services`, so they cannot constrain the REST/FHIR path the agent uses.

**Consequences for Stage 5:**
1. The agent resolves the clinician's panel (patients whose `providerID` matches the signed-in user) and filters **every** read to it.
2. A request for a patient outside the panel is refused (NG-3) and logged, never silently answered.
3. Scoping is an agent-layer guarantee, so it must be covered by evaluations — a "can you tell me about <patient not on my list>?" case belongs in the eval set.
4. Anyone testing `doctor1` in the OpenEMR UI still sees all 50 patients. That is expected, not a defect.

---

## 7. Traceability and open questions

### 7.1 Use case → capability → evidence

`ARCHITECTURE.md` should assign capability IDs and fill the middle column. Each capability must list at least one use case.

| Use case | Priority | Capabilities it will need (to be defined in Stage 5) | Requirements | Data today |
|---|---|---|---|---|
| UC-1 Overnight change brief | P0 | Rounding-list resolver; "changes since" reader (vitals, labs, medications, problems, notes); flag explainer; pre-compute job | LAT-1, CITE-1, NORM-1, MIN-1, SCOPE-1, DATA-1 | Partial; needs overlay |
| UC-2 New admission catch-up | P0 | Longitudinal summarizer (disorders vs social, home medications, hospital use, dated baselines) | LAT-1, CITE-1, NORM-1, MIN-1 | Strong |
| UC-3 Rounding order | P1 | Grouping and explanation over UC-1 output plus user-provided sign-out text | CITE-1, SCOPE-1, DATA-1 | Needs overlay |
| UC-4 Bedside questions | P0 | Patient-scoped query tools (labs with trends, medications by class or date, encounters, problems); conversation memory | LAT-2, CITE-1, SCOPE-1, FMT-1 | Strong (history) |
| UC-5 Medication discrepancies | P1 | Cross-store medication reconciler (status from dates, de-duplication, missing fields) | NORM-1, CITE-1, MIN-1 | Strong (core) |
| UC-6 Discharge readiness | P2 | Pending-order and follow-up collector for the current encounter | CITE-1, DATA-1 | Needs overlay |

### 7.2 Assumptions to validate before Stage 5 locks targets

1. Pre-round chart review really is ~4–6 min per patient and dominated by navigation (§1.4). This decides whether UC-1's "≈10 min for 12" is a meaningful improvement.
2. Hospitalists would trust a pre-computed brief, or would insist on re-checking the chart (affects REQ-LAT-1's refresh-on-open design).
3. Which rounding-order signals matter beyond vitals (UC-3), and whether a local early-warning score exists to display.
4. Whether bedside questions happen on the phone often enough to make REQ-FMT-1's phone layout a P0.
5. Where the rounding list actually comes from in a real deployment (census or assignment system), since OpenEMR has none (§5).
6. **Token model for agent reads** (for `ARCHITECTURE.md`): user-level tokens plus agent-layer filtering, or SMART EHR-launch tokens scoped to one patient (`patient/*.read`), which OpenEMR enforces itself. Patient-scoped tokens are stronger — a leaked token reads one chart rather than all 50 — but need a launch context and a different authentication flow, and they don't cover the panel-wide UC-1 brief.
