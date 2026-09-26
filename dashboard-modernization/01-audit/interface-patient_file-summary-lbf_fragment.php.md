# interface/patient_file/summary/lbf_fragment.php

**Role:** body of each "charted LBF form" card. **Size:** 67 lines.
**Reached from:** jQuery `.load("lbf_fragment.php?formname=…")` once per charted LBF form (demographics.php L728-731).

## Purpose and lifecycle

Checks CSRF, takes `formname` from the query string (L12), finds the patient's most recent instance
of that form (L18-27), and renders it with `lbf_report()` plus a trend link.

## Controls

- **CSRF:** checked.
- **Authorization:** none here. The page skips cards whose `grp_aco_spec` the user fails
  (demographics.php L1547-1550), but this endpoint renders any LBF form named in the URL.
- **Escaping:** `formname` is `attr()`-escaped and bound as a query parameter. The trend link here is
  correct (it uses the form name), unlike the card button on the page (DEM-06).

## Database touches

Reads `forms`, `form_encounter`, and the LBF data via `lbf_report()`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| LBF-01 | High | L4-27 | **No authorization, and the form's own ACO spec is not re-checked**, so any LBF form can be requested by name. |

## What the port keeps

Outside the brief.
