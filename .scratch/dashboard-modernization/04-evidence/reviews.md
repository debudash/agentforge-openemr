# Reviews of the Phase 4 diff

## Security review (`security-review` skill)

Run on the working tree against HEAD `533d5ae`: the legacy fixes, the module change, `flags.php`,
the SPA and the local setup scripts. A sub-agent read every changed and new file. No finding reached
the skill's reporting bar (confidence 8 of 10 or more).

| # | Finding | Confidence | Disposition |
|---|---|---|---|
| S1 | The dev stack serves the bind-mounted repository as its web root, so `dashboard/e2e/.auth/restricted-users.json` (test-user passwords), `dashboard/.env.local` and `dashboard/node_modules` were fetchable over HTTP (200). Found while checking the review's note on `restricted-users.php`. | 10 (reproduced) | **Fixed.** `dashboard/.htaccess` denies the directory, in the same form as `bin/.htaccess`; those URLs now return 500 with no body, and `/public/dashboard/` still returns 200. |
| S2 | Same exposure, outside this change: `copilot/.local-doctor1-pass` returns 200. | 10 | **Reported, not fixed here** (predates this branch; one-line `.htaccess` in `copilot/`). |
| S3 | The Co-Pilot link's "Open this patient here" switch set the session patient without the squad and ViewEvent checks `demographics.php` now makes first, and the mismatch refusal named the linked patient before any such check. | 3 | **Fixed.** The gate checks that the user may view the linked patient (patients/demo, ViewEvent, squad) before naming them or offering the switch, and again before switching. Tests: `test_a_link_to_a_patient_outside_the_users_squad_is_refused_without_naming_them`, `test_a_forged_switch_to_a_patient_outside_the_users_squad_changes_nothing`. |
| S4 | `DashboardFragmentGuard` checks patients/demo, squad and the card ACO but does not dispatch the ViewEvent the page does. The fragments had no check at all before. | 2 | **Deferred.** Recorded here; the ViewEvent's only listener in the repo is the PatientFilter Laminas module. |
| S5 | A meta CSP cannot set `frame-ancestors`. | n/a | **Deferred to 4.6**, where the static host (OpenEMR's Apache) can send the header. |

Checked and held: authorization order in `demographics.php`; the pid each fragment guards; every
stored value in both templates; the switch token (HMAC keyed by the session, bound to the uuid,
`hash_equals`, empty key refused); the redirect target (path on this host only); repeated
`patient=` parameters; `flags.php` (one boolean); the SPA's token handling, paging links, CSP,
GET-only traffic and absence of HTML sinks.

## Code review (`mattpocock-skills:code-review` against `week2-baseline`)

Run against `week2-baseline` (`1ae55bf`; the four commits since are docs) with the working
tree, as two parallel reviewers: Standards (CLAUDE.md coding standards plus the Fowler smell
baseline) and Spec (spec 03, ADRs 0001-0008, the catalog, the brief).

Both reviewers read the tree while the refusal-path red run had the module's page changes
stashed (`red-dashboard-links.txt` needs the pages at HEAD). Their first finding ("§12.1 not wired:
`patient.php`/`demo.php` match HEAD, `flags.php` missing") describes that moment, not the change.
The same script popped the stash; the green run after it (26 passed) and every later run used the
complete tree.

### Standards

| # | Finding | Kind | Disposition |
|---|---|---|---|
| C1 | Preference services' `update($id, int $patientId, $data)` / `delete($id, int $patientId)`: untyped params, two ids side by side (Domain Primitives) | Hard | **Partly fixed.** Now `update(int $id, int $patientId, array $data)` and `delete(int $id, int $patientId)`; six baseline entries for the untyped params removed, eleven offset counts per service lowered. A `PatientId` type is **deferred**: none exists in the codebase, and adding one to a two-caller legacy service is a refactor, not the security fix. |
| C2 | `LinkedPatient::resolveFromDatabase` casts `(int) $pid`; `restricted-users.php` casts `(array)` (Narrow, don't cast) | Hard | **Fixed.** `filter_var(..., FILTER_VALIDATE_INT)`; `is_array()` in the setup script. |
| C3 | New classes call static locators (`OEGlobalsBag::getInstance()`, `EventAuditLogger::getInstance()`, `QueryUtils`, `AclMain`, `PatientSessionUtil`) and emit `header()`/`exit` (Dependency Injection) | Hard | **Accepted, recorded.** Neither the Co-Pilot module nor `demographics.php` has a container; every existing module class (`PanelScope`, `ChartReader`, `DocumentWriter`) uses the same statics. `LinkGate` and `DashboardFragmentGuard` are refusal helpers for entry points. Moving them behind interfaces is follow-up work for the module as a whole. |
| C4 | `LinkGate::enforce` branched on `LinkState` with an if-chain and a fall-through (Exhaustive Matching) | Hard | **Fixed.** `match` without `default`; the mismatch path is its own `never` method. |
| C5 | `LinkedPatient` used `0` / `''` as "absent" (Null Safety) | Hard | **Fixed.** `?int $linkedPid`, `?string $uuid`; the isolated test asserts `null`. |
| C6 | The "may view this patient" check (patients/demo, ViewEvent, squad) is written three times: `demographics.php`, `DashboardFragmentGuard`, `LinkGate::mayOpen` | Smell | **Deferred.** One shared core class would make the module commit depend on the legacy-fix commit; a follow-up once both are merged. |
| C7 | `aclCheckCore('patients','demo','','write')` six times across three cards | Smell | Accepted: each card states its own write rule, as the page's other cards do. |
| C8 | `escapeHtml` in `manage_care_team.html.twig` re-implements `jsText` from `library/js/utility.js` | Smell | Accepted: keeps the fix self-contained and readable in review; could switch later. |
| C9 | Six near-identical `useX` hooks in `dashboard/src/app/queries.ts` | Smell | Accepted: each is resource, params, schema, view model; a generic hook would hide the one line that differs. |
| C10 | `handleFormSubmission` vs `handlePost` name the same job | Smell | Accepted: legacy names kept to keep the security diff small. |
| C11 | ACOs as `array{string, string}`; flag argument `int $success` in `LinkGate::audit` | Smell | Flag argument **fixed** (`bool $allowed`). ACO pairs accepted (the page passes the same shape to `aclCheckCore`). |
| C12 | `LinkedPatient` mixes parsing, lookup and HMAC; `refuse()` echoes HTML | Smell | Accepted: one small class for the gate's one job; the refusal page is four escaped lines. |
| C13 | `enforce(LinkedPatient, int $sessionPid, ...)` repeats the session pid | Smell | Accepted: the pid is needed for audit and naming. |
| C14 | "R1"/"R4" comment tags | Smell | Accepted: they name the spec's rules (spec section 2), which the defense cites. |
| C15 | `restricted-users.php`: redundant `$hashInput`; raw SQL for users | Smell | `$hashInput` is needed (`passwordHash()` takes a reference; now commented). Raw SQL accepted: dev-stack-only setup script, outside PHPStan's paths, not web-reachable. |
| C16 | Module pages read `$_SESSION` directly | Smell | Accepted: pre-existing pattern in both pages, at the entry point. |

### Spec

| # | Finding | Kind | Disposition |
|---|---|---|---|
| P1 | §12.1 wiring missing | Missing | Not a finding (stash during the red run, above). |
| P2 | §4 lists `offline_access`; the app does not request it | Missing | **Deviation, recorded.** A public client in a browser has nowhere safe for a refresh token; a sign-in lasts one access token and the cards say when to sign in again. Noted in `smart.ts` and the defense. |
| P3 | §5 Care Team `status=active`: inactive, proposed and suspended teams were shown | Wrong | **Fixed.** Active teams only; test updated. |
| P3b | Participant status and note not rendered; no "care team note renders as text" test | Missing | FHIR carries neither (API-08, BUG-107). The port's R3 test covers team name, member name and role; the legacy note is covered by the BUG-010 browser test. |
| P4 | Referenced `Medication` not resolved; `patient/Medication.rs` requested but unused | Missing | **Fixed by removal.** OpenEMR never sends `medicationReference` (`FhirMedicationRequestService::populateMedication`); the scope is no longer requested. |
| P5 | R6 "locale-aware": always `ymd` | Partial | **Deferred.** The SPA cannot read `date_display_format` without an API; this install uses 0 (`ymd`), which the app matches. `formatDate` takes the order as a parameter. |
| P6 | BUG-011: `observation_code_text` still taken from the POST | Partial | **Deferred.** The XSS is closed by escaping (test green); deriving the text server-side from the LOINC list is defence in depth, kept with the Medium/Low LEGACY rows. |
| P7 | Scope creep: mismatch audit, switch token, "Signed in as", localStorage collapse, Qty/Refills columns, extra scopes, extra NKA codes | Creep | Kept: the audit and token are the refusal path's controls; "Signed in as" uses `fhirUser`; the collapse state replaces the legacy per-user settings write; Qty and Refills are the legacy Rx table's columns; RelatedPerson/Organization resolve care team names and facilities; the NKA siblings are SNOMED's drug, food and environment variants. |
| P8 | The parity harness explained any prescription or list entry with an end date, even a future one | Wrong | **Fixed.** Explained only when the end date has passed; a future end date stays unexplained. The stack holds no active prescription or list entry with a future end date (checked), so the numbers do not change. |
| P9 | The harness cited BUG-027 (severe allergies) for the "active" rule; the medications empty state used allergy wording | Wrong | **Fixed.** BUG-028; the wording now says the legacy text depends on `list_touch`. |
| P10 | `searchAll` stopped at 20 pages with a `next` link pending and said nothing | Wrong | **Fixed.** `truncated` flag; the card shows "This list is incomplete"; one http test and one card test. |

After these fixes, everything was run again on the final tree: lint, typecheck, 57 Vitest tests,
PHPStan, PHPCS, the isolated suite, the refusal path (26), the legacy reproductions (15), end to
end (4), the full parity harness, the usecases suite and the stage 2 gate.
