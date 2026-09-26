# interface/main/tabs/js/patient_data_view_model.js

**Role:** the Knockout view model behind the identity bar. **Size:** 61 lines.
**Reached from:** `left_nav.setPatient()` in `frame_proxies.js`.

## Purpose and lifecycle

`patient_data_view_model(pname, pid, pubpid, str_dob)` (L22-61) holds four observables, a computed
photo URL (`controller.php?document&retrieve&patient_id=…&document_id=-1&context=patient_picture`),
an observable array of encounters and the selected encounter, kept in sync by a subscription on
`selectedEncounterID` (L45-59). `encounter_data(id, date, category)` (L13-20) is one row.

## Controls

None; it is state. The photo URL encodes the pid (L32).

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| PVM-01 | Low | L22-28 | **DOB and age arrive as one preformatted string** (`str_dob`), so the bar cannot show DOB and age separately or localise them itself. |
| PVM-02 | Low | L47-58 | **Linear scan per encounter selection**; negligible at normal sizes. |

## What the port keeps

The identity bar's data contract (name, pid, pubpid, DOB/age string). The port rebuilds it from
FHIR `Patient` rather than from a string pushed by another page.
