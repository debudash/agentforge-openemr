# src/Patient/Cards/CareExperiencePreferenceViewCard.php

**Role:** the "Care Experience Preferences" card, view and inline edit.
**Size:** 249 lines. **Reached from:** `new CareExperiencePreferenceViewCard($pid)` at demographics.php L1307.

## Purpose and lifecycle

A copy of `TreatmentPreferenceViewCard` with different names, service, LOINC list and card ids. A
line diff after normalising the names shows only the identifiers, titles, the service class and one
commented-out line. Everything in that audit applies here: `handlePost()` saves and deletes during
`getTemplateVariables()`, with `// TODO ACL`, and `CareExperiencePreferenceService::update()`/`delete()`
are scoped by `WHERE id = ?` only (L144, L171 of the service).

## Controls

Same as the treatment card: CSRF checked; **no authorization**; no patient scoping on update/delete.

## Database touches

Reads and writes the care-experience preference table; reads `users` once per row.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| CEC-01 | Critical | handlePost + service L144, L171 | **Any user can edit or void any patient's care-experience preferences** (same defect as TPC-01). |
| CEC-02 | High | getTemplateVariables | **Writes during render** (same as TPC-02). |
| CEC-03 | Low | whole file | **Duplicated class.** |

## What the port keeps

Outside the brief's required set.
