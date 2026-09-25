# interface/main/tabs/templates/patient_data_template.php

**Role:** the **persistent identity bar** in the tabs shell — the element the brief calls the "patient header".
**Size:** ~230 lines (Knockout template in a `<script type="text/html">`). **Reached from:** the tabs shell (`interface/main/tabs/main.php`); shown when `app_view_model.attendant_template_type` is `patient-data-template`.

## Purpose and lifecycle

It renders, for the active patient: a photo (L55-61, falling back to a default image on error), the
name and pubpid in parentheses as a link back to the dashboard (L100-103), a close button (L105-107),
the DOB/age string (L111-113), the encounter controls (history, a dropdown of past encounters with
count, new encounter, the open encounter) (L118-170), and the user's message and portal alerts
(L173 onward). Display style of the name follows the `patient_name_display` global (L69-97).

The data arrives from the dashboard: `setMyPatient()` in demographics.php calls
`left_nav.setPatient(name, pid, pubpid, '', dobString)` and `setPatientEncounter(...)`
(`frame_proxies.js`).

## Controls

Knockout `text:` bindings escape their values. PHP output uses `xla()`/`xlt()`. The photo URL is
built client-side from the pid (`patient_data_view_model.js` L29-39).

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| BAR-01 | Medium | L100-113 | **The bar has no sex and no active status.** The brief's header requires name, DOB, sex, MRN and active status; today's bar shows name, pubpid (MRN), DOB/age and photo. The port must add two fields that have no current UI to match. |
| BAR-02 | Low | L98-109 | **Element names interpolated from PHP variables** (`<$wrapperElement>`); safe because they come from a fixed switch, but fragile. |

## What the port keeps

- **Name** as displayed (first last), **MRN** = pubpid in parentheses, **DOB** in the user's date
  format with **age**, or **"Age at death"** when deceased (demographics.php L926-930).
- **Photo** with fallback.
- The encounter dropdown is shell navigation; the port shows encounter history as its own section if
  that is the chosen extra section.
