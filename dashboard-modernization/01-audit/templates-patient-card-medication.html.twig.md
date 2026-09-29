# templates/patient/card/medication.html.twig

**Role:** the Medications card body (the patient's medication list, not prescriptions).
**Size:** 25 lines. **Reached from:** demographics.php L1180; stats.php L221.

## Purpose and behaviour

Lists `title` and `drug_dosage_instructions` for each active medication-list entry; same two empty
states as problems.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Both fields `|text`-escaped.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-MD-01 | Low | L19-20 | **Dosage instructions only appear when the data source provides them.** The page's source (`PatientIssuesService::search`) and stats.php's (a join on `lists_medication`) differ, so the same medication can show with or without instructions depending on which card renders it. |

## What the port keeps

**Required by the brief (Medications).** Parity: active medication-list entries, name plus dosage instructions. FHIR: `MedicationRequest?intent=plan` (OpenEMR maps the medication list to intent `plan`, `PrescriptionService.php` L203-213).
