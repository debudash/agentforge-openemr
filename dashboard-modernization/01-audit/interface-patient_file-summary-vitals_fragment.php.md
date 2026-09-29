# interface/patient_file/summary/vitals_fragment.php

**Role:** body of the Vitals card. **Size:** 49 lines.
**Reached from:** `placeHtml("vitals_fragment.php", "vitals_ps_expand")` (demographics.php L631), only when the vitals form is registered and the user has `patients/med`.

## Purpose and lifecycle

Checks CSRF, finds the newest non-deleted vitals form for the session patient (L17), prints its date,
and includes `interface/forms/vitals/report.php` to render that one form's values (L32-33), with a
link to the trend graph.

## Controls

- **CSRF:** checked.
- **Authorization:** **none** on the endpoint; the page checks `patients/med` before requesting it.
  No squad check.
- **Escaping:** `text()` on the date; the vitals report escapes its own output.

## Database touches

Reads `form_vitals`, `forms`, and whatever `vitals_report()` reads.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| VTF-01 | High | L9-17 | **No authorization on the endpoint.** |
| VTF-02 | Low | L14 | **Malformed attribute** `id='vitals''`. |
| VTF-03 | Low | L19 | **Comment says "disclosures"**, copied from the disclosures fragment. |

## What the port keeps

This is the recommended **extra section** (see the spec): the latest vital signs — BP, pulse,
temperature, respiration, SpO2, height, weight, BMI — with the date taken. FHIR
`Observation?category=vital-signs` provides them.
