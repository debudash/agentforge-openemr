# templates/patient/card/rx.html.twig

**Role:** the Prescriptions card body.
**Size:** 15 lines. **Reached from:** demographics.php L1245.

## Purpose and behaviour

Prints `content` raw: the HTML produced by the Smarty prescription controller's `fragment` action,
captured by the page with an output buffer after a `chdir()` (DEM-12). If `weno` is true it adds a
"Prescription History" header with an OpenEMR edit button.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. `content` is trusted HTML from Smarty; its escaping is the Smarty template's.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-RX-01 | Low | L6-11 | **The `weno` header never renders**: no caller sets `weno`, and its text is an untranslated literal. |
| TPL-RX-02 | Low | L13 | **Two template engines in one card** (Smarty inside Twig). |

## What the port keeps

**Required by the brief (Prescriptions).** Parity: the active prescriptions list (drug, dose, form, route, interval) the Smarty fragment shows. FHIR: `MedicationRequest?intent=order` (the `prescriptions` table).
