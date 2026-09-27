# Patient dashboard migration: full detail

The complete engineering record behind [PATIENT_DASHBOARD_MIGRATION.md](../PATIENT_DASHBOARD_MIGRATION.md): every rule and how it is enforced, every API constraint, every tradeoff, the legacy fixes and the parity method. The defense at the repo root is the short version; this file is the reference it links to. Paths such as `04-evidence/` are relative to this folder.

---


The patient dashboard's presentation layer, moved from server-rendered PHP to a React and
TypeScript single-page app that reads OpenEMR's FHIR API. The app is in `dashboard/`. OpenEMR serves
the built files from `public/dashboard/`, and the app reads patient data only through the FHIR API,
with its own SMART token.

The work behind it is in `dashboard-modernization/`: a dependency tree of the legacy page
(51 files), a per-file audit, a bug catalog of 110 rows, a migration spec with ten design rules, and
the evidence in `04-evidence/`. Decisions are ADRs 0001-0010 in `docs/adr/`.

## What was built

| Brief | Built |
|---|---|
| Login via OAuth2 / OpenID Connect | SMART App Launch v2, public client with PKCE (S256), `openid fhirUser` plus read-only `patient/*.rs` scopes. Two ways in: standalone (`launch/patient`: the user signs in with their OpenEMR account and picks the patient in OpenEMR's picker), and EHR launch from the chart (`launch`: the chart's patient, no second login; ADR 0009). |
| Patient header: name, DOB, sex, MRN, active status | Name, MRN (the `PT` identifier, i.e. pubpid), DOB, age (or age at death), sex, status, and the signed-in user. |
| Allergies, Problem List, Medications, Prescriptions, Care Team from FHIR | One card each, from `AllergyIntolerance`, `Condition`, `MedicationRequest` (`intent=plan` and `intent=order`) and `CareTeam`, with member, prescriber and facility names read from `Practitioner`, `RelatedPerson` and `Organization`. |
| One more section | Vitals: the latest set from `Observation?category=vital-signs` (ADR 0003). |

The layout follows the legacy page: the three PAMI cards in a row, then Prescriptions, Care Team,
Vitals, in Bootstrap 4.6 as OpenEMR ships it. The app is read-only; inside the chart, Edit opens the
legacy editors (see "Editing" below).

## Why React, TypeScript and Vite

ADR 0001; the alternatives are in spec section 3.

- **React** escapes every value by default. The legacy page runs Twig with autoescape off for the
  whole application, and three templates forgot to escape (stored XSS, BUG-009/010/011). In the
  port, the only way to render HTML is `dangerouslySetInnerHTML`, and lint fails the build on it.
- **TypeScript (strict)** because FHIR JSON is optional fields all the way down. Each response is
  parsed by a Zod schema into a typed view model before a component sees it, so "this field may be
  missing" is a compile error, not a PHP notice at render time.
- **Vite** builds static files. There is no server runtime to secure and nothing between the
  browser and the API.
- **`fhirclient`** (SMART Health IT's reference client) does the OAuth dance, so there is no
  hand-written OAuth. Every request after login goes through one module of ours.
- **Rejected:** Vue and Svelte (smaller SMART/FHIR ecosystem, no offsetting gain); modern Angular
  (shares little with the AngularJS 1.8 already in OpenEMR, heavy for six cards); Next.js or any SSR
  (a second backend holding tokens and PHI); Streamlit (server-side rendering, awkward browser
  OAuth); PHP with htmx (not a framework port, and it keeps the model that produced BUG-003).

## What moving off PHP gained

The audit's worst rows share one cause: the legacy page authorizes rendering, not data. It decides
which cards to draw, and the endpoints behind them trust that decision. The port's ten rules
(spec section 2) turn that around, and each rule is enforced by something that fails when the rule
is broken:

| Rule | Enforced by |
|---|---|
| R1 Nothing is fetched before a token exists; the server authorizes every request | The app renders only a sign-in screen until login completes. A test asserts that no request leaves before then. `src/fhir/http.ts` refuses any URL outside the FHIR base, including paging links. |
| R2 Read-only | `http.ts` is the only network module (lint bans `fetch` everywhere else) and it sends GET only. The end-to-end test records the app's traffic after login: all GET. |
| R3 Text-only rendering | Lint bans `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML` and `document.write`. A test puts `<img onerror>` into every card field and checks that it renders as text. |
| R4 Parse at the boundary; one "active" rule per resource | Zod schemas in `src/fhir/`. An entry that fails its schema is counted and shown ("1 entry could not be read"), never silently dropped, and a list cut off at the page limit says so. |
| R5 Loading, empty, error and data are four states | A test checks that a 500, a 401, a network failure and a non-Bundle response each show the card's error state and a Retry button, never "None". |
| R6 One formatting module | `src/format/dates.ts`, with the legacy age and deceased rules. Tested on midnight, 12-hour and 24-hour clocks, and the month/year boundaries. |
| R7 Accessible toggles | The collapse control is a `<button>` whose `aria-expanded` follows its state, and titles are headings. axe (WCAG 2.1 A/AA) reports no serious or critical violation on the live page. |
| R8 Minimum necessary | No SSN, no name in the window title, `no-referrer`, the token only in the `Authorization` header, and the authorization code removed from the address bar. Tested. |
| R9 Named extension slots | Every card has a `before` and an `after` slot. |
| R10 Clinical-safety rules are tested | Severe and high-criticality allergies are pinned first. Inactive, resolved, refuted and entered-in-error entries never render. "No Known Allergies" is shown only when recorded. |

To check that the tests would catch a regression, 22 rule-carrying lines were broken on purpose
one at a time. Each time, the named test or the lint failed
(`04-evidence/unit-test-mutations.txt`). The same for the four lines ADR 0009 and 0010 added
(`04-evidence/in-chart/unit-test-mutations.txt`).

Other gains:

- **Separation.** The legacy entry point is 2,080 lines of SQL, authorization, HTML, CSS and
  JavaScript, and three of its card classes write to the database while rendering. The port has
  1,950 lines of source in six directories (auth, fhir, format, cards, header, app). Its only
  input is API responses.
- **A published contract.** The data layer is FHIR R4 / US Core, not OpenEMR's table layout.
- **Testability.** Every card is a function of parsed resources. 77 unit tests run in about 5
  seconds with no database and no browser, over responses recorded from the dev stack.

## Tradeoffs

- **Authorization is coarser than the legacy page** (API-01, API-11, CONST). The legacy page checks
  `patients/med`, each issue type and the patient's squad. For this app's tokens the API checks
  none of them: a `patient/`-scoped token skips the user's ACL entirely (API-11, ADR 0010). A user
  restricted by any of these can see more in the port than in the legacy page. A browser client
  cannot enforce what the server does not, so the app says so in its About panel, and the chart
  embeds the app only for users with `patients/med` and the issue ACLs. The real fix is
  server-side.
- **No refresh token.** The app does not ask for `offline_access`, which spec section 4 listed: a
  public client in a browser has nowhere safe to keep one. A sign-in lasts one access token (an
  hour); after that each card says the sign-in expired.
- **One patient per sign-in.** OpenEMR refuses `user/` scopes for public clients (API-06), so the
  token is bound to the patient chosen at login. Opening another patient means signing in again.
  This is narrower than a user-wide token, which suits R8, but it is a workflow change.
- **Served by OpenEMR, not separately** (ADR 0008, superseding 0002). The 4.0 spike found that
  OpenEMR never answers a CORS preflight: `CORSListener` runs after authorization and routing, so
  `OPTIONS` gets a 404 (API-04). Every token-bearing request from another origin fails. The app is
  therefore served same-origin from `public/dashboard/`. No OpenEMR code changed for this, but the
  built files ship inside the OpenEMR image, and the CSP is a `<meta>` tag, which cannot set
  `frame-ancestors`.
- **Parity is limited by what FHIR carries:**
  - `Patient.active` is always true (API-02), so status comes from the deceased fields.
  - `list_touch` is not in FHIR (API-03), so an empty list reads "No allergies recorded", not the
    legacy "Nothing Recorded" or "No Known Allergies", unless NKA was recorded as an entry.
  - `clinical-status` search returns nothing, or a 500 with SQL in the body (API-07), so the port
    filters client-side.
  - CareTeam participants carry no status and no note (API-08), so a member marked inactive is
    still listed. Only active teams are shown.
  - The seven legacy allergy severities arrive only as `criticality` low/high (API-10).
  - `_count` truncates silently (API-09) and is never sent.
- **A second toolchain.** Node and npm where there was none. `dashboard/` has its own `package.json`
  and does not inherit OpenEMR's Node >= 24 requirement.
- **More requests.** One page view becomes one request per card, plus one per referenced
  practitioner or organization. Each is authorized separately, which is the point of R1. TanStack
  Query caches them for the session.
- **No shared session with the chart, standalone.** SMART login does not create an OpenEMR
  interface session. The header's Co-Pilot link lands on OpenEMR's login page unless the user
  already has one (ADR 0006). Opened from the chart (ADR 0009) the app reuses the chart's sign-in
  and hides these links: the chart's patient menu has them.
- **`fhirclient` 2.6.3, not 3.0.0.** 3.0.0 (a week old) ships type declarations that import a file
  it does not contain. 2.6.3 brings 10 moderate `npm audit` advisories: `uuid` < 11.1.1 through
  `xcode`, pulled in by the optional Expo dependencies of `isomorphic-webcrypto`, plus the Expo
  packages that depend on them.
  - Reach, checked: none of these packages is in the shipped bundle. A source-mapped build lists
    exactly 14 packages in the runtime bundle (`04-evidence/npm-audit-reach.txt`), and none is
    `uuid`, `xcode` or `@expo/*`.
  - They exist only in `node_modules` on the build machine, and nothing in the build calls them.
    The advisory is a missing bounds check when a buffer is passed to `uuid` v3/v5/v6.

## Accepted constraints

| Row | Constraint | How it shows |
|---|---|---|
| BUG-007 (API-01) | API authorization is `patients/med`, not per issue type or squad | About panel; this document |
| BUG-012 (API-02) | `Patient.active` is always true | Header status from `deceasedDateTime` / `deceasedBoolean` |
| BUG-014 (API-03) | No `list_touch` in FHIR | "No allergies recorded" / "None"; NKA only as an entry |
| BUG-013 (API-04) | CORS preflight never answered | Same-origin hosting (ADR 0008); reported upstream |
| BUG-044 (API-05) | Public client + PKCE | Proven in the 4.0 spike |
| BUG-043 (API-06) | No `user/` scopes for public clients | `patient/*.rs`; one patient per sign-in |
| BUG-106 (API-07) | `clinical-status` search broken; its 500 leaks SQL | Never sent; "active" decided in `src/fhir/` |
| BUG-107 (API-08) | CareTeam participants carry no status | Former members listed; flagged by the parity harness |
| BUG-108 (API-09) | `_count` truncates silently | Never sent |
| BUG-109 (API-10) | Allergy severity collapsed into criticality | "High criticality", pinned first |
| BUG-110 (API-11) | A `patient/`-scoped token skips the user's ACL | Chart: app only for users with `patients/med` and the issue ACLs (ADR 0010). Standalone: a user with `patients/demo` but not `patients/med` reads the clinical record; `e2e/known-limits.spec.ts` proves it and fails once the API is fixed |

"No backend changes" is read as OpenEMR's backend. Three changes were made outside the port, each
decided in an ADR and kept in its own commit. The third is a deviation from the brief (next
section).

- **Our Co-Pilot module** (ADR 0006). The header links to the Co-Pilot and Demo Data pages with the
  FHIR patient id. The page refuses unless the id is the patient the OpenEMR session has open.
- **The legacy dashboard's Critical and High bugs** (ADR 0004). They are fixed in the PHP page,
  which stays in the product.
- **The chart opens the new dashboard** (ADR 0009, guarded by ADR 0010).

## Deviation from the brief: one OpenEMR change

The brief says the backend is not touched. ADR 0009 changes one OpenEMR page and adds two
settings, so that clicking a patient opens the new dashboard inside the EMR.

**What changed**

| File | Change |
|---|---|
| `library/globals.inc.php` | Two settings under Admin > Globals > Appearance: `patient_dashboard_renderer` (`legacy`, the default, or `smart_app`) and `patient_dashboard_smart_client_id`. |
| `interface/patient_file/summary/demographics.php` | With the SMART app selected, a client ID set, and a user who passes the guard (below): the card area is replaced by a frame that EHR-launches the app for the patient through `interface/smart/ehr-launch-client.php`. Everything above the cards stays: the authorization check, `set_pid`, the identity bar, the header, the patient menu with its module tabs, clinical alerts and popups. |
| `dashboard/` | The app also accepts an EHR launch (`iss` + `launch`). Not an OpenEMR file. |

**Why.** Standalone, the doctor signs in again, picks the patient again and approves again, outside
the chart. Every way of opening a patient (calendar, finder, recent patients, "back to
dashboard") loads `demographics.php`, so changing that one page puts the new dashboard in all of
them, for the patient being opened, with no second login.

**On and off.** Admin > Globals > Appearance > Patient Dashboard Cards. `OpenEMR cards` is today's
page, unchanged; it is the default, and rollback is this one setting. `SMART app` also needs:

- the client ID in Patient Dashboard SMART Client ID;
- the client registered with the `launch` scope and an `initiate_login_uri` of
  `https://<openemr>/public/dashboard/`, and enabled (new clients start disabled);
- for no login or consent screen: the global `oauth_ehr_launch_authorization_flow_skip` (on by
  default) and the client's "skip EHR launch authorization flow" flag.

With no client ID, or a user who fails the guard, the page shows the cards.

**What stays read-only and API-only.** The frame is the only new output. The app still reads every
value through the FHIR API with its own token, sends GET only, and renders text only (R1-R3).
`demographics.php` passes the app nothing but the launch (built by OpenEMR's own
`SmartLaunchController`) and the patient's FHIR id on the frame. The app refuses a token for any
other patient, so a launch that races a patient switch shows an error, not the other patient.

**Editing.** The legacy cards' Edit buttons open OpenEMR's editors; the new cards do the same in
the chart. Allergies, Problems and Medications open `stats_full.php` for that issue type, and
Prescriptions opens the prescription editor dialog (or eRx compose when eRx is on), under the
legacy rules: the first three always, Prescriptions only with patients/rx write or addonly.
`demographics.php` builds every URL and lists the granted actions on the frame
(`data-edit-actions`); the app's button only posts the action's name to its parent, and the page
honours a message only from its own frame, on its own origin, naming a granted action. Writes stay
in OpenEMR's own editors and their permission checks; the app still sends GET only. Standalone,
outside the chart, there is no OpenEMR session to edit through, so the cards have no Edit. Care
Team and Vitals have no Edit: the legacy Care Team edits inline in its own card, and vitals are
entered in an encounter. Tests: `tests/chart-edit.test.tsx` (3) and `e2e/in-chart-edit.spec.ts`
(6, including forged, unknown and outside-the-frame messages).

**The trust flag.** Skipping the authorization flow skips both login and consent for that client:
the app gets every scope it registered, for the patient on screen, as the signed-in user. It is an
admin decision per client, meant for the clinic's own app. The OAuth2/OIDC exchange with PKCE
still runs on every open.

**The chart guard** (ADR 0010). The FHIR API skips the user's ACL for this app's tokens (API-11).
The chart therefore embeds the app only for a user with `patients/med` and the allergy,
medical-problem and medication issue ACLs, the checks the legacy clinical cards make. Anyone else
gets the legacy cards, and no token is issued. Tested: `dashboard/e2e/in-chart.spec.ts`.

## Parity

The parity harness (`dashboard/e2e/parity.spec.ts`) renders both dashboards for every patient on
the dev stack. The legacy one is opened through the tabs shell as doctor1; the port through SMART
login as doctor1. The harness then compares each card: the same items, the same order rules and the
same empty state. Every difference is explained from that patient's own database rows, not by
assumption. A difference with no matching rule fails the run.

Final run on the stack's 50 patients (`04-evidence/parity/parity-report.md`), with no
unexplained difference:

| Card | Match | Explained | Flagged | Unexplained | Items legacy / port |
|---|---|---|---|---|---|
| Header | 48 | 2 | 0 | 0 | 200 / 300 |
| Allergies | 7 | 43 | 0 | 0 | 59 / 59 |
| Problems | 44 | 6 | 0 | 0 | 417 / 417 |
| Medications | 22 | 28 | 0 | 0 | 63 / 63 |
| Prescriptions | 4 | 46 | 0 | 0 | 306 / 63 |
| Care Team | 48 | 1 | 1 | 0 | 2 / 3 |
| Vitals | 10 | 40 | 0 | 0 | 243 / 193 |

The port's header has 100 more items because it adds sex and status for every patient.

The differences, and the rule behind each:

- **Empty-state wording** (allergies 43, medications 28, problems 6). The legacy page shows
  "Nothing Recorded" or "No Known Allergies" according to `list_touch`, which FHIR does not carry
  (API-03). The item lists match.
- **Prescriptions: 243 rows in 46 patients in this run, since restored.** The legacy card is
  "Prescription History": every row flagged `active=1`, including ended ones, which the API reports
  as `completed`. The port first showed active ones only. It now lists active and completed
  prescriptions, active first, with a Status column, and hides stopped ones, as the legacy card
  does. A re-run on the 10 patients with the most prescription history matched the legacy card for
  every item (140 / 140), with no other card changed (`04-evidence/prescription-history/`). The
  50-patient table above predates the change.
- **Vitals: BMI in 40 patients.** The legacy report rounds BMI to a whole number; the port shows
  the recorded value (R6). Every other vital matched.
- **Header: age in 2 patients.** The legacy bar writes "23 month"; the port writes "23 months" (R6).
- **Care Team: name order in 2 patients.** The legacy row copies the name from its edit form's
  option text ("Reyes, Dana"); the port writes "Dana Reyes", as the header does.
- **Care Team, flagged: 1 patient.** The port lists a member marked inactive, because FHIR CareTeam
  participants carry no status (API-08). This one is flagged rather than explained away: the port
  cannot tell a former member from a current one without a server change.

## Legacy fixes

The eleven Critical and High catalog rows are LEGACY except BUG-007 (CONST). Each was reproduced
on the dev stack by the user it is about, with the restricted users of ADR 0005, before it was
fixed:

| Row | Was | Now | Test |
|---|---|---|---|
| BUG-001 | Any user who could open the dashboard could replace a patient's care team | Saving needs patients/demo write; handled before render | `legacy-security.spec.ts` BUG-001 |
| BUG-002 | Any user could add, edit or void any patient's preferences, by row id | patients/demo write required; update and delete scoped `AND patient_id = ?` | BUG-002 / BUG-004 |
| BUG-003 | `set_pid` sent the patient's name, DOB and encounters before the authorization check | patients/demo, the ViewEvent and the squad are checked at the top, before anything else | BUG-003 / BUG-008 |
| BUG-004 | Preference writes ran inside `getTemplateVariables()` | Card forms are handled before rendering; render has no side effects | BUG-002 / BUG-004 |
| BUG-005 | A squad restriction hid only the header | A patient outside the user's squads gets "Not Authorized" and no card | BUG-005 |
| BUG-006 | Vitals, labs, disclosures and LBF fragments answered any signed-in user | Each fragment repeats the page's checks and the card's ACO; LBF only for active LBF layouts | BUG-006 |
| BUG-008 | Unauthorized views changed the session patient and wrote the recent-patients list | Nothing happens before authorization | BUG-003 / BUG-008 |
| BUG-009 | A quote in a stored preference ended the `data-pref` attribute | `data-pref="{{ pref\|json_encode\|attr }}"` | `PatientCardTemplateEscapingTest` |
| BUG-010 | A care team note ran as markup | Every stored value in the row template is escaped before `innerHTML` | BUG-010 (browser) |
| BUG-011 | `observation_code_text` was printed unescaped (filter precedence) | Parenthesised, then `\|text` | `PatientCardTemplateEscapingTest` |

Red and green runs are in `04-evidence/red-*.txt` and `green-*.txt`. Medium and Low LEGACY rows stay
in the catalog, deferred.

## Running it

```bash
# once: register the public client (redirect https://<openemr>/public/dashboard/, patient/*.rs;
#       for the chart also `launch` and initiate_login_uri = the same URL), enable it,
#       and put its id in dashboard/.env.local as VITE_SMART_CLIENT_ID (see .env.example)
cd dashboard
npm ci
npm run build          # writes ../public/dashboard/, served by OpenEMR
npm run build:watch    # during development (not the Vite dev server: it would be cross-origin)
npm run lint && npm run typecheck && npm test      # what CI runs
npm run e2e            # local only: end to end, in-chart, parity, legacy reproductions, known limits
```

The GitLab job `dashboard` runs lint, typecheck and the unit tests. The browser suites need the
OpenEMR dev stack, so they run locally and their reports are committed under `04-evidence/`.

## Not done

- ~~Deploy (4.6).~~ Done 2026-09-26: `build_openemr_image.sh` builds `public/dashboard/` into the
  image (image `8.2.0-dev-949e911` from `week2`); the chart setting is on in production.
- **Upstream reports** for API-04, API-07, API-08, API-11 (drafted in
  `04-evidence/in-chart/upstream-issue-api-acl.md`) and the legacy fixes.
