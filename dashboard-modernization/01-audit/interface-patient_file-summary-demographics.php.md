# interface/patient_file/summary/demographics.php

**Role:** the Medical Record Dashboard. The entry point for everything in this audit.
**Size:** 2,080 lines. PHP, inline JavaScript, inline CSS and HTML in one file.
**Reached from:** the tabs shell when a patient is selected (`?set_pid=`), and from dozens of
"back to dashboard" links (no parameters).

## Purpose

It is the page a clinician lands on after choosing a patient. It establishes that patient as the
session's active patient, pushes the patient's identity and encounter list up into the tabs
shell's identity bar, and renders a two-column page of cards: allergies, problems, medications,
prescriptions, care team, two preference cards, demographics, billing, insurance, messages,
reminders, disclosures, amendments, labs, vitals, LBF form summaries, portal access, photos,
advance directives, clinical reminders, appointments, recalls, tracks and a delete button. About
a third of those cards are empty shells whose bodies are fetched after load from separate
fragment scripts.

The file is also, by accident of structure, the POST target for three editing forms that live
inside cards (care team, and the two preference cards), and for the insurance eligibility check.
Those writes are handled inside card classes while the page renders.

## Lifecycle

The order matters, because several things happen before the authorization check.

1. **Bootstrap (L30-69).** `globals.php` starts the session, connects the database and populates
   `$GLOBALS`. Eight procedural libraries are included for their functions.
2. **Patient resolution (L71-75).** `$pid` is taken from the session, or from `?pid=` if the
   session has none. Nothing checks that the user may see that patient at this point.
3. **Patient switch (L84-94).** With `?set_pid=`, `setpid()` makes it the session patient,
   `PatientService::touchRecentPatientList()` writes it to the user's recent-patients list, and
   `?set_encounterid=` is written into the session as the active encounter.
4. **SMART and card setup (L99-101).** The SMART launch controller registers listeners; the list of
   globally hidden cards is read.
5. **Clinical decision rules (L105-134).** If CDR is on: new allergy/medication conflicts are
   computed and, if any, a `<script>alert(...)</script>` naming the conflicting medications is
   **echoed immediately** — before `<!DOCTYPE>`. Active reminders and all allergy conflicts are
   computed for the popup.
6. **Page-local functions (L138-305).** Eleven global functions are declared: hidden cards, money
   formatting, photo lookups, portal checks, deceased text, image widget.
7. **Data load (L307-363).** Deceased status, whether the vitals form is registered, the full
   `patient_data` row (`*`), employer data, primary insurance.
8. **`<head>` (L379-1049).** Assets, then ~600 lines of inline JavaScript. `setMyPatient()`
   (L916-967) is generated here with the patient's **name, pubpid, DOB and age** and, when
   `set_pid` is present, **every encounter's id, date and category** for this patient.
9. **Authorization (L1054-1061).** Only now: the `ViewEvent` is dispatched (modules may veto) and
   `patients/demo` is checked. If either fails, an "unauthorized" partial is rendered and the
   script exits. Everything emitted in steps 5 and 8 has already been sent.
10. **Squad check (L1068-1072).** If the patient belongs to a squad the user is not in,
    `$thisauth` becomes 0 — which suppresses only the header include (L1074-1077).
11. **Cards (L1089-2053).** Rendered in order, each with its own ACL check (or none; see Controls).
12. **Footer script (L2060-2077)** and a post-page-load event dispatched after `</body>`.

After load, the browser fetches nine fragments by POST with the CSRF token (L605-732) and
injects their HTML with `innerHTML`.

## Controls

**Authorization.** The page-level check is `patients/demo` plus the module `ViewEvent` (L1056-1058).
Per card:

| Card | Check | Lines |
|---|---|---|
| Allergies / Problems / Medications | `aclCheckIssue(type)` | L1095-1097 |
| Prescriptions | `patients/rx` and not disabled | L1098 |
| Care Team | card's ACL `patients/demo`, checked **after** the card is constructed | L1253, L1270-1271 |
| Treatment / Care Experience preferences | **none** | L1280-1329 |
| Demographics / Billing / Insurance | card ACL, **skipped when the ACL is empty** (Billing) | L1357-1360 |
| Messages | `patients/notes` | L1384 |
| Patient Reminders | `patients/reminder` | L1403 |
| Disclosures | `patients/disclosure` | L1424 |
| Amendments | `patients/amendment` | L1447 |
| Labs | `patients/lab` | L1477 |
| Vitals | `patients/med` | L1507 |
| LBF forms | per-form `grp_aco_spec` | L1547-1550 |
| Portal (secondary section) | card ACL, **no empty-ACL guard** | L1601-1605 |
| Photos, Advance Directives, Tracks | **none** | L1640, L1663, L2030 |
| Clinical Reminders | `patients/alert` | L1729 |
| Appointments | `patients/appt` | L1754, L1999 |
| Delete | `admin/super` + global | L2046-2052 |

The squad restriction is applied to the header only (L1074). The fragments enforce nothing
themselves except the notes fragment (see their audits).

**CSRF.** Fragment fetches and settings saves send `csrf_token_form` (L501, L456). The page itself
accepts POSTs without a token check at page level; the care team and preference cards check their
own tokens, the eligibility POST does not (see `InsuranceViewCard`).

**Output escaping.** PHP output uses `text()`, `attr()`, `js_escape()` consistently in this file.
Twig autoescaping is off app-wide (`TwigContainer.php:70`), so every template escapes by hand.

## Database touches

Reads: `globals` (L141), `documents`/`categories`/`categories_to_documents` (L169, L189, L1667-1683),
`patient_data` (L231, L242, L264, L349, L548), `patient_access_onsite` (L252), `registry`
(L344, L2028), employer and insurance (L351-363), `form_encounter` + calendar categories (L937, L956),
`layout_group_properties` (L721, L1537), `prescriptions` (L1187), `amendments` (L1450),
`procedure_report`/`procedure_order` (L1481), `form_vitals` (L1511), `forms` (L1558, L2031),
calendar events (L1774, L1934, L1963), `openemr_postcalendar_categories` (L1840), `medex_recalls`
(L1899), plus everything the services and CDR functions read.

Writes: session (`pid`, `encounter`, `alert_notify_pid`, `disablePreviousNameAdds`), the
recent-patients list (L89), and, through card classes during render, the care team, preferences,
patient contact record and eligibility responses.

## Globals, session and superglobals

`$_GET['pid']`, `$_GET['set_pid']`, `$_GET['set_encounterid']` are read directly (L74, L84-93,
L918, L954-955). `$GLOBALS` is passed wholesale into `new PortalCard($GLOBALS)` (L1590; the
constructor takes no arguments). Procedural functions communicate through globals:
`fetchNextXAppts()` sets `global $resNotNull` (L36, L1897); `image_widget()` reads `global $pid,
$web_root` (L313). The Twig function `imageWidget` (`TwigExtension.php:185`) calls
`image_widget()`, which exists only when this file has been included.

## Dependencies

Twelve PHP libraries and services listed in `00-tree.md`; jQuery, Bootstrap 4 and the dialog
library in the browser; the eRx vendor's SOAP endpoints via `interface/soap_functions` (L554,
L574). **No COM objects.**

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| DEM-01 | Critical | L111-133, L916-966, L1056-1061 | **PHI is sent before the authorization check.** With `?set_pid=`, the response already contains the patient's name, pubpid, DOB/age and every encounter's id/date/category (in `setMyPatient()`), and any medication/allergy conflict alert, before `patients/demo` and the `ViewEvent` are checked. An unauthorized user gets the "unauthorized" message appended to a page whose source already holds the data. Verified by code reading; not reproduced live. |
| DEM-02 | High | L84-94, L105-134 | **Side effects run for unauthorized users.** `set_pid` changes the session patient and writes the recent-patients list; CDR computations run — all before L1056. |
| DEM-03 | High | L1068-1077 | **The squad restriction hides only the header.** For a patient in a squad the user is not in, `$thisauth` is set to 0 but every card after L1089 still renders. |
| DEM-04 | Medium | L90-93, L954-964 | **`set_encounterid` is not tied to the patient.** Any encounter id is written into the session as the active encounter and opened, even one belonging to another patient; the `form_encounter` lookup has no `pid` condition. Wrong-patient documentation risk. |
| DEM-05 | Medium | L1110-1113 (+ stats.php L39, services) | **Three definitions of "active" on one page.** The PAMI cards filter `outcome != 1 AND (enddate empty OR future)`; Allergies are fetched through a different service than Problems/Medications; `stats.php` uses `enddate` empty only. The same issue can show in one card and not another. |
| DEM-06 | Medium | L1568 | **LBF "Trend" always opens vitals.** The button for every charted LBF form links to `trend_form.php?formname=vitals`. |
| DEM-07 | Medium | L1186 | **eRx "Current Medications" card never renders.** It depends on `$display_current_medications_below`, which is only assigned in `stats.php` — a separate request. |
| DEM-08 | Medium | L547-603 | **eRx sync blocks and can loop.** Two synchronous XHRs run on page load; if either response lacks the word "Nothing" the page reloads, which reruns them. An error page from the vendor reloads forever. |
| DEM-09 | Medium | L1850-1858, L1970-1978 | **Appointment times are wrong in edge cases.** Past appointments print "pm" in 24-hour mode (the meridiem is set before the format check); upcoming appointments print "0:MM am" at midnight in 12-hour mode. |
| DEM-10 | Medium | L1889, L1991 | **Provider names double-escaped.** `uname` is `text()`-escaped here and escaped again by the template, so "O'Brien" displays as `O&#039;Brien`. |
| DEM-11 | Medium | L494-535 | **Fragment errors are shown as content.** `fetchHtml()` never checks `response.ok`; a 500 page or a CSRF failure message is injected into the card body. |
| DEM-12 | Medium | L1233-1242 | **Prescription card renders via a `chdir()` hack.** The working directory is changed to the web root to run a Smarty controller into an output buffer, and never restored (`$cwd` is saved and unused). Any later relative path resolves from the wrong directory. |
| DEM-13 | Medium | L937-947, L1511, L1672-1702, L1726, whole file | **Unbounded and repeated queries per view.** All encounters are loaded into JS; `SELECT *` on `form_vitals` just to test existence; nested per-category document queries; `resolve_rules_sql()` on every view; ~25 event dispatches, ~18 of them for card injections that are never rendered. |
| DEM-14 | Low | L1897, L2017 | **`$resNotNull` is always true.** It records whether the statement handle is non-null, not whether rows came back; the Recall card and the appointments "Add" gate depend on it and are effectively unconditional. Misleading, not currently harmful. |
| DEM-15 | Low | L1827-1870 | **Overflow appointment colour never applied.** `$apptStyle` is computed and never passed to the template; display-set colours 3 and 4 are dead. |
| DEM-16 | Low | L1268, L1376 | **Placeholder `btnLink => 'test'`** for Care Team and section cards. |
| DEM-17 | Low | L1223, L1130, L1154 etc. | **Untranslated labels.** "Prescription History" is shown untranslated; button labels are passed as English literals. |
| DEM-18 | Low | L131-133 | **Script emitted before `<!DOCTYPE>`**, forcing quirks mode when an allergy conflict exists. |
| DEM-19 | Low | L449, L670-671, L961 | **Implicit JS globals and leftover logging.** `$mode`, `encurl`, the handler's `event`, `console.log`. |
| DEM-20 | Low | L683 | **Inconsistent CSRF parameter** (`csrf_token` vs `csrf_token_form`) for the rule editor. |
| DEM-21 | Low | L138-147 | **Hidden-cards setting read with raw SQL** on the `globals` table, bypassing `OEGlobalsBag`. |
| DEM-22 | Low | L149-163, L418-435, L2063-2068 | **Dead code.** `print_as_money()` is never called; `deleteme()` is marked unused and puts the CSRF token in a URL; `$condition_str` and `$showEligibility` are never set. |
| DEM-23 | Low | L311-341 | **`image_widget()` builds HTML strings** with a case-sensitive, duplicated extension list; files with no extension take the substring from position `false`. |
| DEM-24 | Low | L1451, L1841 | **`$result` is reused.** The patient row is overwritten by the amendments statement and the category loop; latent, as nothing reads it afterwards today. |

## What the port keeps

- The **set of cards and their order**, and each card's **empty states**: "No Known Allergies" vs
  "Nothing Recorded" (driven by `getListTouch()`), "None" for problems and medications.
- The **per-card authorization** as a requirement, including the squad rule the page intends but
  does not enforce (DEM-03). The port cannot enforce it client-side; see the spec.
- **Severity highlighting** on allergies (severe, life-threatening, fatal).
- The **identity bar contract**: name, MRN (pubpid), DOB and age, "Age at death" when deceased.
- The **deceased banner** text rules in `deceasedDays()` (L282-305).

## What the port drops

- Everything that runs before authorization (DEM-01, DEM-02).
- Writes on a read page: the port is read-only (the brief is presentation only).
- The fragment/innerHTML pattern, the eRx SOAP sync, the Smarty hack, `chdir`, synchronous XHR.
