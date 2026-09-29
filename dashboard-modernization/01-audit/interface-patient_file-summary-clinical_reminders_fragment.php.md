# interface/patient_file/summary/clinical_reminders_fragment.php

**Role:** body of the Clinical Reminders card. **Size:** 24 lines.
**Reached from:** `placeHtml(…, true, true)` when CDR and the clinical reminder widget are on (demographics.php L634-635).

## Purpose and lifecycle

Checks CSRF and calls `clinical_summary_widget($pid, "reminders-due", …)` for the session patient
(L14). All logic lives in `library/clinical_rules.php`.

## Controls

**CSRF:** checked. **Authorization:** none here; the page requires `patients/alert` (L1729).

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| CRF-01 | Medium | L9-14 | **No authorization on the endpoint.** Lower sensitivity than the clinical fragments; same pattern. |

## What the port keeps

Outside the brief.
