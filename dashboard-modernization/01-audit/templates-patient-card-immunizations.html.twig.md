# templates/patient/card/immunizations.html.twig

**Role:** the Immunizations card body.
**Size:** 17 lines. **Reached from:** stats.php L294.

## Purpose and behaviour

One link per immunization that opens the edit page via `load_location(url)`. The link text is
`i.cvx_text`, raw.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. `i.url` was built with `attr_js()` in PHP. `cvx_text` comes from the `codes` table
(reference data), so the raw print is low risk.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-IM-01 | Medium | L12 | **Prints the wrong field.** stats.php computes `field` (custom list title or CVX text) and an escaped `immunization_data`; the template prints raw `cvx_text`, so custom-list immunizations and entries without a CVX code are blank links (STA-02). |
| TPL-IM-02 | Low | L12 | **No date shown**, though stats.php prepared one. |

## What the port keeps

Candidate extra section. FHIR `Immunization?patient=` provides vaccine code/display and occurrence date.
