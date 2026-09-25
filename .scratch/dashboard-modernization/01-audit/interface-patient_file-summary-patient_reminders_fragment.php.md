# interface/patient_file/summary/patient_reminders_fragment.php

**Role:** body of the Patient Reminders card. **Size:** 23 lines.
**Reached from:** `placeHtml(…, false, true)` when CDR and the patient reminder widget are on (demographics.php L714-715).

## Purpose and lifecycle

Checks CSRF and calls `patient_reminder_widget($pid)` (L13). The logic is in `library/reminders.php`.

## Controls

**CSRF:** checked. **Authorization:** none here; the page requires `patients/reminder` (L1403).

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| PRF-01 | Medium | L9-13 | **No authorization on the endpoint.** |

## What the port keeps

Outside the brief.
