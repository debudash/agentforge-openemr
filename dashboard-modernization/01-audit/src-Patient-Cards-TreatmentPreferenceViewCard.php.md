# src/Patient/Cards/TreatmentPreferenceViewCard.php

**Role:** the "Treatment Intervention Preferences" card, view and inline edit.
**Size:** 249 lines. **Reached from:** `new TreatmentPreferenceViewCard($pid)` at demographics.php L1281.

## Purpose

It lists the patient's treatment intervention preferences (LOINC-coded observations with a coded,
free-text or yes/no answer, a status and a note) and handles the inline form that adds, edits and
voids them. It was added for USCDI v4/v5 preference data.

## Lifecycle

The constructor sets options and creates `TreatmentInterventionPreferenceService` (L24-29).
`getTemplateVariables()` (L64-116) — called while the page renders the card — first calls
`handlePost()` (L69), then loads the LOINC list and the patient's preferences, and looks up each
author's name with one query per row (`getUserDisplay`, L123-131). `handlePost()` (L154-187): on a
POST with `pref_type=treatment_intervention` it checks the CSRF token and then **saves**
(`update($id)` or `insert`) or **deletes** (`delete($id)`, which sets status `entered-in-error`).

## Controls

- **Authorization:** the options array uses the key `'auth' => ['patients','demo']` (L35) where the
  base class expects `'acl'`, so the card has no ACL; the page renders it without a check
  (demographics.php L1280-1301). The template variables hard-code `'auth' => true` and
  `'can_write' => true` with `// TODO ACL` (L105-106). **Saving and deleting check no permission.**
- **CSRF:** checked on POST (L163).
- **Patient scoping:** `update($id, …)` and `delete($id)` in the service are `WHERE id = ?` only
  (TreatmentInterventionPreferenceService.php L132-144, L167-173). The id comes from the POST body.

## Database touches

Reads the preference table, the LOINC answer lists, `users` (once per row). Writes the preference
table (insert, update, status change) — during render.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPC-01 | Critical | L154-187 + service L132-173 | **Any user can edit or void any patient's preferences.** No permission is checked, and update/delete are scoped by row id only, so a POST from patient A's dashboard with patient B's preference id changes B's record. Verified by code reading; not reproduced live. |
| TPC-02 | High | L69 | **Writes happen inside `getTemplateVariables()`**, i.e. while rendering. A render is not idempotent. |
| TPC-03 | Medium | L35 | **Wrong option key (`auth` instead of `acl`)**, so the card carries no ACL. |
| TPC-04 | Low | L123-131 | **One user lookup per preference row.** |
| TPC-05 | Low | whole file | **Near-duplicate of CareExperiencePreferenceViewCard.php** (a diff differs only in names). |

## What the port keeps

Outside the brief's required set (read-only view would map to FHIR `Observation` with the
preference LOINC codes).
