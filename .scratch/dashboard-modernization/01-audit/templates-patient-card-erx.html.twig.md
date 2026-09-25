# templates/patient/card/erx.html.twig

**Role:** the eRx "Current Medications" card body.
**Size:** 19 lines. **Reached from:** demographics.php L1208 (never reached, DEM-07); stats.php L170.

## Purpose and behaviour

Lists active prescriptions: drug and dosage escaped, then `form`, `unit`, `route`, `interval` printed
raw — they come from `generate_display_field()`, which returns escaped HTML.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-ER-01 | Low | L10 | **`form`/`unit` printed with no separator**, e.g. `tablet` + `mg` → `tabletmg`. |

## What the port keeps

Superseded by the Prescriptions card in the port.
