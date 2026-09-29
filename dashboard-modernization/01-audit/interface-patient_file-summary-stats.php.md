# interface/patient_file/summary/stats.php

**Role:** fragment that fills `#stats_div` after the dashboard loads.
**Size:** 344 lines. **Reached from:** `placeHtml("stats.php", "stats_div", true)` (demographics.php L606), POST with CSRF.

## Purpose

It renders the cards the main page does not: every issue type other than allergy, medication and
medical problem (surgeries, dental, custom types from `ISSUE_TYPES`), an eRx "Current Medications"
card, the Immunizations card, an "Old Medication" card, and a card for two legacy spreadsheet
forms (Treatment Protocols, Injury Log). It predates the Twig cards on the main page; the three
PAMI types were moved out ("refactored", L130) and the rest stayed here.

## Lifecycle

It reads the session pid (L6), checks the CSRF token (L15), then iterates `ISSUE_TYPES` minus the
three moved types (L129-136). For each type the user may see (`aclCheckIssue`, L140) it loads the
list and renders it with the problems or medication template. eRx state threads through the loop
in `$old_key` and `$erx_upload_complete`, so a "Current Medications" card is emitted in the
iteration *after* the medication type (L144-174). Then the two spreadsheet forms (L229-260), then
Immunizations (L263-304), then Old Medication (L307-333).

## Controls

- **CSRF:** checked (L15).
- **Authorization:** per issue type for the list cards (L140). **None** for Immunizations (L263) and
  the spreadsheet forms. Immunizations passes `'auth' => true` (L301), so every viewer gets the
  edit link.
- **Escaping:** `immunization_data` is pre-escaped with `text()` (L277) and `field` with
  `htmlspecialchars` (L284), but the template prints neither of them (STA-02).

## Database touches

Reads `lists` (+ `lists_medication`), `prescriptions`, `form_treatment_protocols`/`form_injury_log`
(via `SHOW TABLES LIKE`, then a join on `forms`), `immunizations` + `codes` + `code_types`, and
`list_options` via `getListItemTitle`/`generate_display_field`. No writes.

## Globals and session

`$pid` from the session; `ISSUE_TYPES` from `OEGlobalsBag`; the eRx globals `erx_enable`,
`erx_medication_display`, `erx_allergy_display`. `$display_current_medications_below` is assigned
here (L126). It is the variable demographics.php tests in its own, separate request (DEM-07).

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| STA-01 | Medium | L263-304 | **Immunizations have no authorization check** and always offer "Edit" (`'auth' => true`). |
| STA-02 | Medium | L277-291 + immunizations.html.twig L12 | **Computed immunization names are thrown away.** The loop works out `field` (custom list or CVX text) and an escaped summary, but the template prints the raw `cvx_text`. Custom-list immunizations and entries without a CVX code show as empty links. |
| STA-03 | Medium | L290 | **CSRF token in a GET URL** for every immunization edit link; it leaks through referrers and server logs. |
| STA-04 | Medium | L322-324 | **Old Medication card has no id.** It passes `'label'` instead of `'id'`, so the collapse target is `#` and collapsing does nothing. |
| STA-05 | Low | L243-252 | **Spreadsheet-form card is broken.** The `$formRws` typo drops the template name, the loop keeps only the last row, the title is always "Injury Log", and both forms share `id="injury_log"`. |
| STA-06 | Low | L176, L195 | **Each issue list is queried twice.** |
| STA-07 | Low | L39-44 | **"Active" here means `enddate` empty**, a third definition on the same page (see DEM-05). |
| STA-08 | Low | L64-70, L97-111 | **Dead code.** `$rowclass` is computed and unused (and undefined when both dates are set); `getPrescriptions()` is never called. |

## What the port keeps

The **Immunizations** card is a candidate extra section. Its rule: rows not added erroneously,
newest first; the display text is the CVX short name, or the custom list title when that global is
on. The other issue types (surgery, dental, custom) are outside the brief's required set.
