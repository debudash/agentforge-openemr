# 02 — Bug catalog

Phase 2 of the patient dashboard modernization. Every finding from the per-file audits in
`01-audit/`, condensed to one row: severity, category, a concrete mitigation, and who resolves it.
Findings reported in more than one file are merged into one row that cites all of them. The
catalog is generated from the audit tables by a script that fails if any audit finding is missing,
so the two cannot drift.

**151 audit findings → 110 catalog rows.**

## How to read it

**Severity**

| | Meaning |
|---|---|
| Critical | A user with ordinary dashboard access can read PHI they are not allowed to see, or change another record, with no special setup. |
| High | A security flaw that needs one precondition (a restricted user, stored input, a crafted request), or a missing check on a PHI endpoint. |
| Medium | A functional bug users can see, wrong or missing clinical data, a privacy excess, or a defence-in-depth gap. |
| Low | Cosmetic, dead code, maintainability, or a latent bug nothing triggers today. |

**Disposition** — who resolves it

| Code | Meaning | Rows |
|---|---|---|
| PORT | Designed out: the new dashboard has no equivalent code path. | 4 |
| REQ | A requirement the port must meet (parity, or a rule the legacy page promised and broke). Each becomes a test in Phase 4. | 12 |
| LEGACY | Fix in the PHP dashboard, which stays in the product alongside the port. Separate change, candidate for upstream. | 78 |
| CONST | Accepted constraint of "no backend changes"; stated in the spec and in `PATIENT_DASHBOARD_MIGRATION.md`. | 12 |
| NONE | No action: dead or cosmetic legacy code the port does not reuse. | 16 |

A row can carry two codes (e.g. `LEGACY + PORT`: the legacy page needs a fix, and the port avoids
the defect by design).

**Verification.** Every row cites the file and lines it came from, and was verified by reading the
cited code. In Phase 4 the Critical and High LEGACY rows (BUG-001 to BUG-011, except the CONST row
BUG-007) were **reproduced live** on the dev stack, as the restricted users of ADR 0005, before they
were fixed: see `04-evidence/red-*.txt` and `green-*.txt`. BUG-106 to BUG-110 were found in Phase 4.

## Summary

| Severity | Rows |
|---|---|
| Critical | 3 |
| High | 9 |
| Medium | 33 |
| Low | 65 |

**The pattern behind the worst rows:** the dashboard authorizes *rendering*, not *data*. The page
decides which cards to draw; the endpoints behind them (fragments, card POST handlers) assume the
page already checked. Three separate write paths run inside card rendering with no permission
check, and three template sinks print stored values unescaped under an app-wide `autoescape =>
false`. A port that fetches data from endpoints that authorize every request, and renders only text
nodes, removes the whole class — which is the case for moving the presentation layer rather than
patching it.

## Catalog

| ID | Sev | Category | Finding | Mitigation | Disposition | Audit refs |
|---|---|---|---|---|---|---|
| BUG-001 | Critical | AuthZ | Saving a care team needs no permission | Require `patients/demo` write (and the squad check) inside `handleFormSubmission()`; move the save to its own POST endpoint instead of the card constructor. | LEGACY | CTC-01 |
| BUG-002 | Critical | AuthZ / IDOR | Any user can edit or void any patient's preferences | Check write ACL in `handlePost()`; scope service `update`/`delete` with `WHERE id = ? AND patient_id = ?`; move writes out of render. | LEGACY | TPC-01, CEC-01 |
| BUG-003 | Critical | AuthZ / Privacy | PHI is sent before the authorization check | Move the `patients/demo` + ViewEvent check to the top of the script, before `set_pid` handling, CDR and any output; emit nothing patient-specific until it passes. Port: the SPA renders nothing until the token and patient read succeed. | LEGACY + PORT | DEM-01 |
| BUG-004 | High | Architecture / Integrity | Writes happen inside `getTemplateVariables()` | Handle POSTs in a controller before rendering; `getTemplateVariables()` must be side-effect free. | LEGACY | TPC-02, CEC-02 |
| BUG-005 | High | AuthZ | The squad restriction hides only the header | Treat `$thisauth == 0` after the squad check as a full stop (render the unauthorized partial and exit), not a header-only switch. Port: cannot enforce squads client-side (see API-01). | LEGACY + CONST | DEM-03 |
| BUG-006 | High | AuthZ | No authorization on the endpoint | Each fragment re-checks the same ACL (and squad) the page used to show the card, and LBF re-checks the form's `grp_aco_spec`. Port: no fragments; data comes from API routes that enforce their own ACL. | LEGACY + PORT | DSF-01, LBD-01, VTF-01, LBF-01 |
| BUG-007 | High | AuthZ / API constraint | The API's authorization is coarser than the dashboard's | Document in the spec and the defense: the port inherits the API's `patients/med` granularity and cannot hide per-issue-type or squad-restricted data. Mitigation without backend change: request only the scopes the dashboard needs; show an explicit note in the app. Real fix is server-side (upstream). | CONST | API-01 |
| BUG-008 | High | AuthZ / Integrity | Side effects run for unauthorized users | Same fix as DEM-01: no session change, recent-list write or CDR run before authorization. | LEGACY | DEM-02 |
| BUG-009 | High | XSS (attribute) | Attribute injection through `data-pref='{{ pref\|json_encode }}'` | Use `\|attr` on the JSON (`data-pref="{{ pref\|json_encode\|attr }}"`) or `json_encode` with `JSON_HEX_APOS\|JSON_HEX_QUOT`. | LEGACY | TPL-PR-02 |
| BUG-010 | High | XSS (stored) | Stored XSS through the care-team note | Build rows with `textContent`/`createElement`, or escape with `jsText()` before `innerHTML`; never interpolate DB values into template literals bound to `innerHTML`. Port renders text nodes only. | LEGACY + PORT | TPL-CT-01 |
| BUG-011 | High | XSS (stored) | Stored XSS through `observation_code_text` | Parenthesise: `(pref.observation_code_text ?? pref.code_display)\|text`; derive `observation_code_text` server-side from the LOINC list instead of trusting the hidden input. | LEGACY | TPL-PR-01 |
| BUG-012 | Medium | API constraint | `Patient.active` is always `true` | Do not show `Patient.active` as status (always true). Header status = "Active" unless `deceasedDateTime`/`deceasedBoolean` is set, then "Deceased <date>". Defined in the spec. | CONST + REQ | API-02 |
| BUG-013 | Medium | API constraint | CORS preflight is never answered | Serve the dashboard same-origin from `public/dashboard/` (ADR 0008). Upstream: register CORSListener above the authorization listener, fix L69, and restrict origins to registered clients. | CONST | API-04 |
| BUG-014 | Medium | API constraint / Data | "No Known Allergies" vs "Nothing Recorded" is not in the API | Empty allergy list shows "No allergies recorded"; an NKA entry (SNOMED 716186003) shows "No Known Allergies". Document the difference from the legacy card's list_touch rule. | CONST + REQ | API-03 |
| BUG-015 | Medium | Architecture | Prescription card renders via a `chdir()` hack | Render the prescription list from `PrescriptionService` in Twig; remove `chdir()` or restore the directory in a `finally`. | LEGACY | DEM-12 |
| BUG-016 | Medium | Architecture | Depends on functions declared in the entry page and on `global $pid` | Move the portal checks into `PortalCard` (or a service) and take `pid` in the constructor. | LEGACY | PTC-01 |
| BUG-017 | Medium | Architecture | Global Twig function depends on a page-local PHP function | Move `image_widget()` into a class the Twig function can call; do not depend on a page-local function. | LEGACY | TPL-PH-02 |
| BUG-018 | Medium | AuthZ | Wrong option key (`auth` instead of `acl`) | Use the `acl` option key so the card carries `patients/demo`. | LEGACY | TPC-03 |
| BUG-019 | Medium | AuthZ | Immunizations have no authorization check | Gate Immunizations on `patients/med` (as Vitals is) and pass the real write permission to `auth`. | LEGACY | STA-01 |
| BUG-020 | Medium | AuthZ | Write before authorization | Move the Completed handler below the notes ACL + squad check and require notes write. | LEGACY | PNF-01 |
| BUG-021 | Medium | AuthZ | No authorization anywhere | Re-check the card's ACL in the fragment (Tracks needs one assigned first). | LEGACY | TAF-01, CRF-01, PRF-01 |
| BUG-022 | Medium | AuthZ | No authorization for the card | Gate Advance Directives on the documents ACL. | LEGACY | TPL-AD-02 |
| BUG-023 | Medium | AuthZ / Clinical safety | `set_encounterid` is not tied to the patient | Look up the encounter with `WHERE encounter = ? AND pid = ?` and ignore it when it does not belong to the patient. | LEGACY | DEM-04 |
| BUG-024 | Medium | AuthZ / Privacy | Financial data without a financial permission | Give the Billing card an ACL (`acct/rep` or `acct/bill`). | LEGACY | BVC-01 |
| BUG-025 | Medium | CSRF | Cross-site request forgery on an outbound transaction | Add the CSRF token to the eligibility form and check it before `requestEligibleTransaction()`; move the trigger to its own endpoint. | LEGACY | IVC-01, TPL-IN-02 |
| BUG-026 | Medium | CSRF / Privacy | CSRF token in a GET URL | POST the token in a form body instead of a URL. | LEGACY | STA-03, TPL-DL-01 |
| BUG-027 | Medium | Clinical safety | Severe allergies are not pinned to the top | Sort severe, life-threatening and fatal allergies first, as the template's own header promises. Port: required behaviour with a test. | LEGACY + REQ | TPL-AL-01 |
| BUG-028 | Medium | Data correctness | Three definitions of "active" on one page | One definition of "active" (clinical status active, not resolved, end date empty or in the future) in one service method used by every card. Port: `clinical-status=active` on every query. | REQ | DEM-05, STA-07 |
| BUG-029 | Medium | Data correctness | LBF "Trend" always opens vitals | Use `formname=<grp_form_id>` for each LBF card's Trend link (as `lbf_fragment.php` L48 already does). | LEGACY | DEM-06 |
| BUG-030 | Medium | Data correctness | Appointment times are wrong in edge cases | Format times with one helper (`oeFormatTime`) for both lists; set meridiem only in 12-hour mode; show 12, not 0, at midnight. | LEGACY | DEM-09, TPL-AP-03 |
| BUG-031 | Medium | Data correctness | Computed immunization names are thrown away | Print the computed `field` (escaped) in the template, not raw `cvx_text`; show the date. | LEGACY | STA-02, TPL-IM-01 |
| BUG-032 | Medium | Dead code / Data | eRx "Current Medications" card never renders | Compute the eRx flag in the page itself or drop the card; today it can never render. | LEGACY | DEM-07 |
| BUG-033 | Medium | Error handling | Fragment errors are shown as content | Check `response.ok`; render an error state in the card; stop the spinner. Port: every card has loading, empty and error states. | LEGACY + REQ | DEM-11, TPL-LD-01 |
| BUG-034 | Medium | Escaping / Display | Provider names double-escaped | Escape once, at output: drop `text()` in PHP (L1889, L1991) and keep `\|text` in the template. | LEGACY | DEM-10, TPL-AP-01 |
| BUG-035 | Medium | Extensibility | Injected module content is never rendered | Render `prependedInjection`/`appendedInjection` in `card_base` via the macro, or stop dispatching the events. Port: expose named slots per card so the extension idea survives. | LEGACY + REQ | TPL-CB-04, TPL-MC-01, TPL-PO-01 |
| BUG-036 | Medium | Integrity | Viewing the dashboard writes to the database | Create the contact record on first *edit*, not on view. | LEGACY | CTC-02 |
| BUG-037 | Medium | Markup / Performance | Nested `<html><head>` and a second `setupHeader()` mid-body | Remove the nested `<html><head>` and load the date picker once in the page header. | LEGACY | TPL-CT-02, TPL-PR-03 |
| BUG-038 | Medium | Parity gap | The bar has no sex and no active status | Port adds sex (`Patient.gender`) and a status field (see API-02) to the header; the legacy bar is unchanged. | REQ | BAR-01 |
| BUG-039 | Medium | Performance | Unbounded and repeated queries per view | Load only what is rendered (lazy option lists, `EXISTS` instead of `SELECT *`, bounded encounter list, batch user lookups); skip `CardRenderEvent` dispatches while nothing renders injections. Port: one request per card, cached per session. | LEGACY + PORT | DEM-13, CTC-03, TPC-04 |
| BUG-040 | Medium | Performance / Error handling | eRx sync blocks and can loop | Async requests; reload at most once per page view; treat non-success responses as errors, not as "changed". | LEGACY | DEM-08 |
| BUG-041 | Medium | Privacy | Full subscriber SSN displayed | Mask the SSN (last 4) on the dashboard; full value only on the edit page with write access. | LEGACY | IVC-02, TPL-IN-01 |
| BUG-042 | Medium | UI bug | Old Medication card has no id | Pass `id` (not `label`) for the Old Medication card. | LEGACY | STA-04 |
| BUG-043 | Low | API constraint | Public clients may not hold `user/` scopes | Request `patient/*.rs` scopes; the token covers the one patient chosen at login. | CONST | API-06 |
| BUG-044 | Low | API constraint | Public clients are supported | Prove public client + PKCE end to end as rewrite step 1 before building cards. | CONST | API-05 |
| BUG-045 | Low | Accessibility | `aria-expanded="true"` is constant | `aria-expanded` follows the collapsed state; use a `<button>` for the toggle. Port: required. | LEGACY + REQ | TPL-CB-02 |
| BUG-046 | Low | Architecture | Two template engines in one card | Replace the Smarty fragment with a Twig list (see DEM-12). | LEGACY | TPL-RX-02 |
| BUG-047 | Low | CSRF | Inconsistent CSRF parameter | Use `csrf_token_form` consistently. | LEGACY | DEM-20 |
| BUG-048 | Low | Clarity | `… or isApiAllowed == true` binds loosely | Parenthesise the intended condition. | LEGACY | TPL-PO-02 |
| BUG-049 | Low | Code quality | Implicit JS globals and leftover logging | Declare with `let`/`const`, take `event` as a parameter, remove `console.log`. | LEGACY | DEM-19 |
| BUG-050 | Low | Code quality | Hidden-cards setting read with raw SQL | Read `hide_dashboard_cards` through `OEGlobalsBag`. | LEGACY | DEM-21 |
| BUG-051 | Low | Code quality | `image_widget()` builds HTML strings | Lower-case the extension before matching; handle no extension. | LEGACY | DEM-23 |
| BUG-052 | Low | Code quality | `$result` is reused | Use distinct variable names for the patient row and later result sets. | LEGACY | DEM-24 |
| BUG-053 | Low | Code quality | Comment says "disclosures" | Fix the comment. | NONE | VTF-03 |
| BUG-054 | Low | Code quality | A second Twig container per request | Reuse the page's Twig container; drop unused variables. | NONE | HDR-01, HDR-02 |
| BUG-055 | Low | Code quality | `getViewArgs()` returns the template path | Rename `getViewArgs()`; provide the display fields the template reads. | LEGACY | CTC-04, CTC-05 |
| BUG-056 | Low | Code quality | `ACLMain` vs `AclMain` | Consistent class name; set options once. | NONE | DVC-01, DVC-02 |
| BUG-057 | Low | Code quality | Listens to every SectionEvent | Add the card only to the secondary section; construct without `$GLOBALS`; handle a missing layout row. | LEGACY | PTC-02, PTC-03, PTC-04 |
| BUG-058 | Low | Code quality | Constructor takes no arguments | Drop the unused argument; write the condition as `if (!zhAclCheck(...)) continue;`. | NONE | MNU-03, MNU-04 |
| BUG-059 | Low | Code quality | Element names interpolated from PHP variables | Map the display style to fixed template fragments. | NONE | BAR-02 |
| BUG-060 | Low | Code quality | Leftover `{{ a }}` after the loop | Remove the leftover `{{ a }}`. | LEGACY | TPL-AD-01 |
| BUG-061 | Low | Code quality | CSS value through an HTML escaper | Validate the colour as a CSS colour value. | NONE | TPL-AP-02 |
| BUG-062 | Low | Code quality | `\|attr` used in text context | Use `\|text` in text context. | NONE | TPL-SL-01 |
| BUG-063 | Low | Code quality | `.editOnly` class | Remove the unused class. | NONE | TPL-CT-03 |
| BUG-064 | Low | Code quality | Delegated handlers are bound once per card instance | Scope handlers to the card's own section. | LEGACY | TPL-PR-04 |
| BUG-065 | Low | Config | Count hard-coded to 3 | Read the count from a global (as messages do). | NONE | DSF-04 |
| BUG-066 | Low | Data correctness | The join multiplies rows | Pick the newest report per order, then its first code deterministically (`ORDER BY` + `LIMIT 1`). | LEGACY | LBD-02 |
| BUG-067 | Low | Data correctness | `GROUP BY form_name` with a non-aggregated `form_id` | Group by `form_id` (or select `MAX(form_id)`), so the link target is deterministic. | LEGACY | TAF-02 |
| BUG-068 | Low | Data correctness | Dosage instructions only appear when the data source provides them | One data source for medications, always including dosage instructions. Port: `dosageInstruction[0].text`. | REQ | TPL-MD-01 |
| BUG-069 | Low | Dead code | Overflow appointment colour never applied | Pass `$apptStyle` to the template or delete it. | LEGACY | DEM-15 |
| BUG-070 | Low | Dead code | Placeholder `btnLink => 'test'` | Remove the placeholder `btnLink => 'test'`. | LEGACY | DEM-16 |
| BUG-071 | Low | Dead code | Dead code | Delete: `print_as_money()`, `deleteme()`, `$condition_str`/`$showEligibility` readers, `getPrescriptions()`, `$rowclass`, `appointments_past.html.twig`, `demographics.html.twig`, empty `eligibility.html.twig`. | NONE | DEM-22, STA-08, TPL-APP-01, TPL-DM-01, TPL-EL-01 |
| BUG-072 | Low | Dead code | `$showEligibility` is set and never returned | Return the flag or remove the page's reader. | LEGACY | IVC-03 |
| BUG-073 | Low | Dead code | Unused private method | Remove the unused method or share it with the page. | NONE | IVC-05 |
| BUG-074 | Low | Dead code | Blocks `card_title` and `card_header_actions` override nothing | Remove the non-existent block overrides. | NONE | TPL-PR-05 |
| BUG-075 | Low | Display | Empty severity renders as "()" | Omit the parentheses when severity is empty. | LEGACY + REQ | TPL-AL-02 |
| BUG-076 | Low | Display | `form`/`unit` printed with no separator | Separate form and unit with a space. | LEGACY | TPL-ER-01 |
| BUG-077 | Low | Display | No date shown | Show the administered date. | LEGACY | TPL-IM-02 |
| BUG-078 | Low | Documentation | Header comment says "Patient Portal card" | Fix the copied header comments. | NONE | TPL-DC-01, TPL-DL-02, TPL-EX-01 |
| BUG-079 | Low | Error handling | `die()` mid-render | Log and fall back to the standard menu instead of `die()`. | LEGACY | MNU-02 |
| BUG-080 | Low | Integrity | Identity is pushed by whichever page calls it | Only the page that set the session patient should push identity; check pid against the session. | LEGACY | FPX-01 |
| BUG-081 | Low | Maintainability | `$resNotNull` is always true | Rename to what it means or use the row count; nothing depends on it today. | NONE | DEM-14 |
| BUG-082 | Low | Maintainability | Near-duplicate of CareExperiencePreferenceViewCard.php | Extract one `PreferenceViewCard` parameterised by type and service. | LEGACY | TPC-05, CEC-03 |
| BUG-083 | Low | Markup | Script emitted before `<!DOCTYPE>` | Emit the conflict alert inside the page's `<head>` script. | LEGACY | DEM-18 |
| BUG-084 | Low | Markup | Malformed table | Fix the malformed tags, quote attributes, give each fragment a unique container id. | LEGACY | PNF-02, PNF-03, DSF-03, VTF-02, TAF-03, TPL-IN-03, TPL-BL-01 |
| BUG-085 | Low | Markup | Generic element ids | Prefix ids (`insurance-primary`). | LEGACY | TPL-IN-04 |
| BUG-086 | Low | Parity / Data | DOB and age arrive as one preformatted string | Port builds DOB and age separately from `Patient.birthDate` and formats them locally. | REQ | PVM-01 |
| BUG-087 | Low | Parity note | Only the title is shown | None: parity is title-only; the port may add onset date as an enhancement, flagged as such. | NONE | TPL-MP-01 |
| BUG-088 | Low | Performance | Each issue list is queried twice | Reuse the first `getListData()` result. | LEGACY | STA-06 |
| BUG-089 | Low | Performance | Linear scan per encounter selection | None needed. | NONE | PVM-02 |
| BUG-090 | Low | Privacy | Patient name in the window title | Keep `WindowTitleAddPatient` off in shared-screen settings; port does not put names in the title. | REQ | FPX-02 |
| BUG-091 | Low | Robustness | `0 + $_REQUEST['docid']` | Validate `docid` with `filter_var(..., FILTER_VALIDATE_INT)`. | LEGACY | PNF-04 |
| BUG-092 | Low | Robustness | `$event[1]` is undefined | Guard `$event[1]` (use the whole event name when there is no hyphen). | LEGACY | DSF-02 |
| BUG-093 | Low | Robustness | Unknown `policy_type` key | `$policy_types[$type] ?? false`. | LEGACY | IVC-04 |
| BUG-094 | Low | Robustness | `\|date` on an unparsable value throws | Guard the date filter (`\|date` only on valid values). | LEGACY | TPL-PR-06 |
| BUG-095 | Low | UI bug | Spreadsheet-form card is broken | Fix `$formRws`, collect rows into a list, title and id per form. | LEGACY | STA-05, TPL-TP-01 |
| BUG-096 | Low | UI bug | Encounter link targets frame `RBot` | Open the encounter through `top.navigateTab`/`left_nav.loadFrame`, not frame `RBot`. | LEGACY | LBD-03 |
| BUG-097 | Low | UI bug | Collapse state never persists: | Read the setting with the card's real id. | LEGACY | BVC-02 |
| BUG-098 | Low | UI bug | Class names run together: | Add the missing space before `card_bg_color`. | LEGACY | TPL-CB-01 |
| BUG-099 | Low | UI bug | Links open "add recall" without the patient or recall id | Pass the patient (and recall) id to the recall board. | LEGACY | TPL-RC-01 |
| BUG-100 | Low | UI bug | `btnClass` is always empty | Fix the `btnCLass` key. | LEGACY | TPL-AM-01 |
| BUG-101 | Low | UI bug | Photos gated on the wrong setting | Gate the photo loop on `patientPhotoCategoryName`. | LEGACY | TPL-PH-01 |
| BUG-102 | Low | UI bug | Click handler on the `<li>` | Bind the handler to the anchor, or read `closest('a')`. | LEGACY | TPL-IN-05 |
| BUG-103 | Low | XSS (config) | `onclick` from the menu JSON is printed unescaped | Escape `on_click` with `attr()` or whitelist it. | LEGACY | MNU-01 |
| BUG-104 | Low | i18n | Untranslated labels | Wrap visible labels in `xl()`. | LEGACY | DEM-17, TPL-RX-01 |
| BUG-105 | Low | i18n / Code quality | Button visibility keys off English labels | Decide button visibility from `canAdd()`/`canEdit()`, not label text. | LEGACY | TPL-CB-03 |
| BUG-106 | Medium | API constraint / Info leak | `clinical-status` search does not work, and its failure leaks SQL | Port: never send `clinical-status`; fetch the category and apply the one "active" rule in `src/fhir/` (R4). Upstream: implement the parameter for Condition and AllergyIntolerance, and stop returning exception messages from `ExceptionHandlerListener`. | CONST | API-07 |
| BUG-107 | Medium | API constraint / Clinical safety | CareTeam participants carry no status and no note | Port: list every participant, and say in the defense that former members cannot be told apart. The parity harness flags each occurrence. Upstream: map member status to `period.end` (or drop inactive members) and the note to an extension. | CONST | API-08 |
| BUG-108 | Low | API constraint | `_count` truncates silently | Port: never send `_count`; follow `next` links on the same server only. | CONST | API-09 |
| BUG-109 | Low | API constraint / Data | Allergy severity is collapsed into criticality | Port: show criticality ("High criticality") and pin high-criticality allergies first; the legacy severity word is not available. Upstream: send `reaction.severity`. | CONST | API-10 |
| BUG-110 | High | AuthZ / API constraint | A patient-scoped token skips the user's ACL | Chart: embed the app only for users with `patients/med` and the allergy, problem and medication issue ACLs; everyone else gets the legacy cards (ADR 0010). Standalone: not mitigable in a browser client; a characterization test records the leak. Upstream: apply the route's gacl checks to `users`-role tokens on patient requests (`04-evidence/in-chart/upstream-issue-api-acl.md`). | CONST | API-11 |

## Systemic note

Twig autoescaping is disabled for the whole application (`src/Common/Twig/TwigContainer.php:70`,
`['autoescape' => false]`). It is recorded in every template audit rather than as a finding of its
own, because turning it on is an application-wide change far outside this work — but it is the
root cause of the XSS rows above, and the port's framework must escape by default (see the spec).
