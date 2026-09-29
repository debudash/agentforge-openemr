# interface/patient_file/summary/labdata_fragment.php

**Role:** body of the Labs card. **Size:** 63 lines.
**Reached from:** `placeHtml("labdata_fragment.php", "labdata_ps_expand")` (demographics.php L627), unconditionally; the div exists only with `patients/lab`.

## Purpose and lifecycle

Checks CSRF, then shows the most recent lab: procedure name, collection date and encounter
(L17-41), plus a link to the full lab page.

## Controls

- **CSRF:** checked.
- **Authorization:** **none.** The page gates the card on `patients/lab` (L1477); the endpoint does
  not. No squad check.
- **Escaping:** `text()`, `attr_url()`.

## Database touches

Reads `procedure_report`, `procedure_order`, `procedure_order_code`. No writes.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| LBD-01 | High | L8-25 | **No authorization on the endpoint.** |
| LBD-02 | Low | L17-25 | **The join multiplies rows** (one per order code) and the first wins, so the "most recent" procedure name is arbitrary among codes on the same order. |
| LBD-03 | Low | L41 | **Encounter link targets frame `RBot`**, which does not exist in the tabs UI. |

## What the port keeps

"Most recent lab" is a candidate extra section; FHIR `DiagnosticReport` or
`Observation?category=laboratory` can serve it.
