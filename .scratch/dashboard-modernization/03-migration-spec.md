# 03 — Migration spec

Phase 3 of the patient dashboard modernization: the route, the stack and a phased plan for a
dashboard that **designs the bug catalog out** rather than porting it. It leans on
`00-tree.md` (what exists), `01-audit/` (how it behaves, file by file) and `02-bug-catalog.md`
(what is wrong with it). References like BUG-003 point into the catalog; DEM-01 and similar
point into the audits.

**Status:** decisions made 2026-09-25 (§12). Ready for Phase 4.

---

## 1. What we are building

From the brief (`requirements/…Modernize the Patient Dashboard.pdf`):

> Port the dashboard to a modern framework of your choosing, consuming OpenEMR's existing REST and
> FHIR API as your data layer. You are not touching the backend. You are not redesigning the
> interface. … Feature parity with the original is the standard.

| Required | Source in today's dashboard | Port |
|---|---|---|
| Login via OAuth2 / OpenID Connect | session cookie from `interface/login` | SMART App Launch, authorization code + PKCE |
| Patient header: name, DOB, sex, MRN, active status | tabs-shell identity bar (`patient_data_template.php`); has no sex or status (BAR-01) | header component from FHIR `Patient` |
| Allergies | `allergies.html.twig` | FHIR `AllergyIntolerance` |
| Problem List | `medical_problems.html.twig` | FHIR `Condition` |
| Medications | `medication.html.twig` (medication *list*) | FHIR `MedicationRequest?intent=plan` |
| Prescriptions | `rx.html.twig` + Smarty fragment | FHIR `MedicationRequest?intent=order` |
| Care Team | `manage_care_team.html.twig` | FHIR `CareTeam` |
| One more section | — | **Vitals** (recommended, see §6) |
| `PATIENT_DASHBOARD_MIGRATION.md` | — | the graded defense, written from §3 and §9 |

**Not in scope:** every other card (22 exist; see `00-tree.md`), all editing, the patient menu's
target pages, the legacy dashboard's own fixes (catalog rows marked LEGACY; see §10).

---

## 2. What the audit changes about the target

The catalog's worst rows share one cause: **the legacy page authorizes rendering, not data.**
It decides which cards to draw; the endpoints behind them trust that decision (BUG-006), three
write paths run inside card rendering with no permission check (BUG-001, BUG-002, BUG-004), and
three stored values reach the page unescaped under an app-wide `autoescape => false` (BUG-009,
BUG-010, BUG-011). PHI is emitted before the authorization check runs (BUG-003).

So the target is not "the same page in React". It is a presentation layer with ten rules, each
traceable to catalog rows. These rules are the design; everything after this section implements
them.

| # | Rule | Designs out |
|---|---|---|
| R1 | **Authorization lives in the API.** The app fetches nothing before it holds a token, and every data request is authorized by the server. The client never decides who may see what. | BUG-003, BUG-006, BUG-008 (PORT) |
| R2 | **Read-only.** The app issues only GET requests. No forms, no POST, no write scopes. | BUG-001, BUG-002, BUG-004, CTC-02 |
| R3 | **Text-only rendering.** Values are rendered as text nodes by the framework's default escaping. `dangerouslySetInnerHTML` and `innerHTML` are banned by a lint rule that fails CI. | BUG-009, BUG-010, BUG-011, the systemic autoescape note, MNU-01 |
| R4 | **Parse at the boundary.** Every FHIR response is parsed by a schema into a typed view model before any component sees it. One module owns "active" for each resource. | DEM-05/STA-07, TPL-MD-01 |
| R5 | **Every card has four states:** loading, empty, error, data. An error is shown as an error, never as content. | DEM-11, TPL-LD-01 |
| R6 | **One formatting module** for dates, times, age, "age at death" and relative deceased text, locale-aware. | DEM-09, PVM-01, DEM-10 |
| R7 | **Accessible by construction:** collapse toggles are buttons with a live `aria-expanded`; headings are real headings. | TPL-CB-02 |
| R8 | **Minimum necessary:** no SSN or identifiers beyond the MRN; no patient name in the window title; no PHI in URLs, query strings or logs. | IVC-02, FPX-02, STA-03 |
| R9 | **Named extension slots** before and after each card body, so the module-injection idea the legacy page dispatches but never renders has somewhere to go. | TPL-CB-04 |
| R10 | **Clinical-safety rules are tested, not commented:** severe allergies first; one "active" definition; empty states that distinguish "none known" from "nothing recorded" where the data allows. | TPL-AL-01, API-03 |

---

## 3. Stack

### Recommendation: React 19 + TypeScript (strict) + Vite, as a static single-page app

| Layer | Choice | Why |
|---|---|---|
| Language | TypeScript, `strict` | The data is FHIR JSON with optional fields everywhere. The type checker catches "this field may be missing" at build time, which is exactly the class of bug PHP's untyped arrays let through (`$result['provider']` null access, DEM-24, IVC-04). |
| UI | React 19 | Escapes by default (R3). Components map one-to-one onto cards. Largest ecosystem for healthcare UI and for the SMART tooling below. |
| Build | Vite | Static output (HTML + JS + CSS) that any web server can host; fast local dev. No server runtime to secure. |
| SMART / OAuth | `fhirclient` (SMART Health IT's JS client) | Implements SMART App Launch: standalone and EHR launch, PKCE, token storage and refresh, and a FHIR request helper. Using the reference client beats hand-rolling OAuth. |
| Data fetching | TanStack Query | Per-card request, caching, retry, and the loading/error/data states R5 needs, without writing them by hand. |
| Boundary parsing | Zod schemas per resource (R4), typed with `@types/fhir` | "Parse, don't validate" (the repo's own coding standard) applied to API responses. |
| Styling | Bootstrap 4.6 CSS (the version OpenEMR ships) | The brief says do not redesign. Using the same CSS keeps the look; no component library. |
| Tests | Vitest + Testing Library + MSW (recorded FHIR fixtures); Playwright against the dev stack | Unit tests per card rule; end to end through the real OAuth flow and API, and the parity harness (§7). Playwright only; not the stack's Selenium container (decision 7). |
| Lint | ESLint with `react/no-danger` as an error, TypeScript ESLint | Enforces R3 in CI. |

### What moving off PHP gains

- **Separation the legacy page does not have.** Today one 2,080-line file mixes SQL, business
  rules, authorization, HTML, CSS and JavaScript, and three card classes write to the database
  while rendering. The port's only inputs are API responses; it cannot write, and it cannot skip
  an authorization check because it performs none of its own.
- **Escaping by default instead of by discipline.** Twig here runs with autoescape off, so every
  template must remember to escape. Three places forgot. React inverts that.
- **Types at the data boundary.** FHIR resources become typed view models once, at the edge.
- **Testability.** Each card is a function of a parsed resource; it can be tested without a
  database, a session or a browser.
- **A standards-based data layer.** FHIR R4 / US Core means the dashboard's contract is a
  published standard, not OpenEMR's table layout.

### What it costs (the tradeoffs, stated for the defense)

- **Authorization granularity drops to what the API enforces** (API-01). The legacy page checks
  per issue type and per squad; the API checks `patients/med`. A client cannot enforce what the
  server does not. See §8.
- **Parity limits in the data.** `Patient.active` is always true (API-02); "No Known Allergies"
  vs "Nothing Recorded" is not in FHIR (API-03). Handled explicitly, not hidden.
- **A second deployable** (static assets) and a build toolchain (Node) where there was none.
- **More requests.** One page load becomes one request per card (6-8), each authorized
  separately. That is the price of R1; it is also cacheable.
- **Session model changes.** SMART tokens replace the PHP session cookie; embedding back into the
  tabs shell (if wanted later) needs an EHR launch rather than a shared session.

### Alternatives considered

| Option | Verdict |
|---|---|
| **Vue 3 / Svelte** | Both fine technically. Smaller ecosystem for SMART/FHIR tooling and fewer reviewers who know them; no advantage that outweighs that. |
| **Angular (modern)** | OpenEMR already carries AngularJS 1.8, which argues for continuity, but modern Angular shares little with it; heavier for eight cards. |
| **Next.js / any SSR** | Adds a server between the browser and the API: a second backend holding tokens and PHI, which the brief rules out in spirit ("not touching the backend") and which R1 does not need. |
| **Streamlit (Python)** | The usual demo default here, but a poor fit: it renders on a Python server (reintroducing server-side presentation and a second backend holding tokens), and browser OAuth/SMART flows are awkward. |
| **Keep PHP, add htmx / Alpine** | Not a "modern framework" port as the brief asks, and it keeps the server-rendered model that produced BUG-003. |

**Decided (§12):** React + TypeScript + Vite.

---

## 4. Route: how the app is reached and authenticated

### Hosting

| Option | How | Pros | Cons |
|---|---|---|---|
| A. Separate static service | Local: Vite dev server on `http://localhost:5173`. Railway: a new static service serving the built files. | Clean separation; independent deploys. | **Does not work** (4.0 spike): every token-bearing FHIR call fails its CORS preflight (API-04). |
| **B. Served by OpenEMR (decided, ADR 0008)** | Built into `public/dashboard/`, served at `https://<openemr>/public/dashboard/`. Local: `vite build --watch` into the bind-mounted folder. | Same origin: no CORS. Proven end to end by the spike. No OpenEMR code change. | Ships inside the OpenEMR image; the defense explains that OpenEMR serves the files and the app still reads only through the API. |

### Authentication: SMART App Launch v2, public client with PKCE

1. **Register** the app once as an OAuth client in OpenEMR (Admin → System → API Clients, or
   dynamic registration), **public** (no secret; `ClientRepository.php` L56), with redirect URI
   `https://<openemr>/public/dashboard/` per environment. Omit `token_endpoint_auth_method`:
   sending `none` is rejected (`AuthorizationController.php` L274), and omitting it is what makes
   the client public.
2. **Standalone launch** (primary): the user opens the app → `fhirclient` discovers
   `/.well-known/smart-configuration` → redirects to OpenEMR's authorize page → the user logs in
   with their OpenEMR credentials and **selects a patient** (`launch/patient`) → authorization code
   → token (PKCE `S256`) with the patient in context.
3. **EHR launch** (secondary, later): the app is registered as a SMART app, so the existing SMART
   launch card on the legacy dashboard (`smart_launch.html.twig`) can open it with the current
   patient. No code beyond `fhirclient`'s EHR launch handler.

**Scopes** (read-only, R2): `openid fhirUser launch/patient offline_access` plus
`patient/Patient.rs patient/AllergyIntolerance.rs patient/Condition.rs
patient/MedicationRequest.rs patient/CareTeam.rs patient/Practitioner.rs patient/Observation.rs`.
OpenEMR refuses `user/` scopes for public clients (`AuthorizationController.php` L325-330);
`patient/` scopes with a provider login work, and bind every request to the patient chosen at
login (`BearerTokenAuthorizationStrategy.php` L259-265). Verified in the 4.0 spike, except
whether `patient/Practitioner.rs` resolves CareTeam members (the spike patient had no care team).

**Tokens** live where `fhirclient` keeps them (session storage for the tab), never in URLs or
logs (R8). A strict Content-Security-Policy in the app's `index.html` (meta tag, since OpenEMR
serves the files) limits script sources to the app itself.

---

## 5. Data layer: card by card

Each card is one query, one schema, one view model, one component. "Active" rules are written
once, in the schema module (R4).

### Patient header

| Field | FHIR | Rule |
|---|---|---|
| Name | `Patient.name` (use `official`, else first) | "Given Family", as the legacy bar shows |
| DOB and age | `Patient.birthDate` | formatted by R6; age in years (months under 2) |
| Sex | `Patient.gender` | display the value set's label (Male / Female / Other / Unknown) |
| MRN | `Patient.identifier` where `type.coding.code = PT` | legacy: pubpid in parentheses |
| Status | **not** `Patient.active` (always true, API-02) | "Active", or "Deceased — date (relative)" from `deceasedDateTime`/`deceasedBoolean`, using the legacy wording (`deceasedDays()`, demographics.php L282-305); "Age at death" replaces age |
| Photo | not in the brief | out of scope for v1 |

### Allergies — `GET AllergyIntolerance?patient={id}&clinical-status=active`

- Row: `code.text` (or first coding's display); severity from `reaction[].severity` (mild /
  moderate / severe) and `criticality` (high) → label in parentheses; reaction manifestation in a
  secondary line or tooltip.
- **Pin severe and high-criticality allergies to the top**, and highlight them (R10, TPL-AL-01 —
  the legacy template promised this and did not do it).
- Empty: an entry coded "No known allergy" (SNOMED 716186003) → "No Known Allergies"; no entries →
  "No allergies recorded" (API-03; the legacy "Nothing Recorded" vs NKA distinction came from
  `list_touch`, which the API does not expose).

### Problem List — `GET Condition?patient={id}&category=problem-list-item&clinical-status=active`

- Row: `code.text`. Parity is title-only (TPL-MP-01); onset date may be added as a clearly
  labelled enhancement.
- Empty: "None".

### Medications — `GET MedicationRequest?patient={id}&intent=plan&status=active`

- The medication *list* (`lists` type medication maps to intent `plan`, `PrescriptionService.php`
  L203-213).
- Row: medication name (`medicationCodeableConcept.text` or referenced `Medication`) and
  `dosageInstruction[0].text` — always, from one source (TPL-MD-01).
- Empty: "None".

### Prescriptions — `GET MedicationRequest?patient={id}&intent=order&status=active`

- The `prescriptions` table (intent `order`, `PrescriptionService.php` L156-157).
- Row: drug, dose, form, route, frequency, with a space between every part (TPL-ER-01), plus
  prescriber and date written.
- Empty: "None".

### Care Team — `GET CareTeam?patient={id}&status=active` (+ `Practitioner`, `RelatedPerson` references)

- Team name and status badge; per participant: name (resolved reference), type (provider /
  related person), role, period start ("since"), status, note.
- Rendered as text (R3); the legacy stored-XSS path (BUG-010) cannot exist.
- Empty: "No care team".

### Extra section: Vitals — `GET Observation?patient={id}&category=vital-signs&_sort=-date&_count=…`

- Latest set: BP (systolic/diastolic component), pulse, temperature, respiration, SpO2, height,
  weight, BMI, with the date taken and units as recorded. Mirrors the legacy Vitals card
  (`vitals_fragment.php`), so parity is checkable.

---

## 6. Why Vitals for the extra section

The legacy dashboard has a Vitals card, so parity can be measured rather than asserted; US Core
defines vital-signs Observations precisely; and it is clinically the most-glanced section after
PAMI. Alternatives, all supported by the API: Appointments (legacy card exists; more formatting
rules, DEM-09), Immunizations (legacy card is buggy, STA-02, so "parity" is ambiguous), Encounter
history (lives in the shell, not the dashboard).

---

## 7. Parity: how "feature parity" is proven

A **parity harness**, not screenshots by eye:

1. For each of the dev stack's patients, render the legacy dashboard as `doctor1` and extract
   the list items of each in-scope card from the HTML.
2. Render the port for the same patient and extract the same lists from its DOM.
3. Compare per card: same items, same order rules, same empty state. Differences must match a
   documented rule change (R10, API-02, API-03) or they fail.

The harness is a Playwright test (decision 7) that runs on the host against the dev stack, in
the same process as the end-to-end tests, and its report goes into the evidence for the defense.
It opens the legacy dashboard through the tabs shell (the `pat` frame), as a user does, because
`demographics.php` loaded on its own calls `parent.left_nav`.

Why not the dev stack's Selenium container: a browser inside Docker sees `localhost` as its own
container, but OpenEMR's OAuth address (`site_addr_oath`) is `https://localhost:9300`, so the
SMART login cannot complete from there. Playwright on
the host reaches both. Selenium stays in the stack for OpenEMR's own E2E suite and browser
debugging; nothing of ours used it.

Local only: the GitLab pipeline has no OpenEMR stack, so CI runs the unit tests (Vitest) and the
harness and end-to-end tests run on the dev stack, with their reports committed. The stack's
certificate on 9300 is self-signed; tests set `ignoreHTTPSErrors`.

---

## 8. Accepted constraints (CONST rows)

| Constraint | Consequence | How it is surfaced |
|---|---|---|
| API-01: API authorization is `patients/med`, not per issue type or squad | Users restricted by issue type or squad see more in the port than in the legacy page | Stated in the defense; request only needed scopes; a note in the app's About panel. The real fix is server-side and is proposed as an upstream issue, not done here. |
| API-02: `Patient.active` always true | Header status derived from deceased fields | §5 header rule |
| API-03: no `list_touch` in FHIR | "No Known Allergies" only when recorded as an entry | §5 allergy rule |
| API-04: CORS preflight is never answered (404), `Allow-Methods` is malformed, any origin is reflected with credentials | No cross-origin browser app can call the API with a token | Served same-origin from `public/dashboard/` (ADR 0008); reported upstream |
| API-05: public client + PKCE | Proven by the 4.0 spike | — |
| API-06: public clients may not hold `user/` scopes | Each token covers one patient, chosen at login | `patient/*.rs` scopes (§4); the header shows the patient in context |

---

## 9. Phased plan

Each phase ends with something runnable and a check that it works. Nothing is deployed to
Railway without the owner's approval (the existing publish gate).

| Phase | Deliverable | Done when |
|---|---|---|
| **4.0 Spike** | A throwaway page that completes SMART standalone launch with PKCE against the local dev stack and prints the selected `Patient`. | Token obtained, `Patient` read, scopes confirmed. Unblocks API-05. **Done** (`04-evidence/spike-4.0.md`); found API-04 and API-06. |
| **4.1 Scaffold** | `dashboard/` app: Vite + React + TS strict, ESLint (`react/no-danger` = error), Vitest, MSW, the R6 formatting module, card chrome with R5 states and R7 toggles, R9 slots. CI job added to the pipeline. | Lint, typecheck and tests pass in CI on an empty dashboard. |
| **4.2 Header + auth** | Launch flow, token handling, header component. | Header matches the legacy bar for all dev patients, plus sex and status. |
| **4.3 Clinical cards** | Allergies, Problems, Medications, Prescriptions, Care Team — one vertical slice each: schema → view model → component → tests (fixtures) → live check. | Each card's rules (§5) have tests; parity harness green for that card. |
| **4.4 Vitals** | Extra section. | Same bar as 4.3. |
| **4.5 Parity + hardening** | Full parity harness run; Playwright end to end through real login; CSP; accessibility check; error boundary. | Harness report committed; no unexplained differences. |
| **4.6 Deploy** | Built app in the Railway OpenEMR image under `public/dashboard/` (how it gets there is decided at this step), OAuth client registered for the production URL. | **Owner approval**, then the live check. |
| **4.7 Defense** | `PATIENT_DASHBOARD_MIGRATION.md` at the repo root: framework choice (§3), gains, tradeoffs, constraints (§8), parity evidence (§7), the audit and catalog as the basis. | Committed on this branch; merged to `week2` with the rest. |

### Tests written first (from the catalog)

Before the cards they protect:

- A value containing `<img src=x onerror=alert(1)>` in an allergy, problem, medication and care
  team note renders as text (R3; the class behind BUG-009/010/011).
- Severe / high-criticality allergies sort first (TPL-AL-01).
- An `inactive` or `resolved` allergy, problem or medication never renders (R4).
- A 500, a 401 and a network failure each render the card's error state, not content (R5).
- Midnight and 24-hour formatting (DEM-09); a name with an apostrophe renders literally (DEM-10).
- No request is sent before a token exists (R1); the app never issues a non-GET request (R2).

---

## 10. The legacy dashboard's own bugs

The port does not fix the PHP page, which stays in the product. The catalog's **LEGACY** rows
(78) include three Critical and several High security defects in code that is live today
(BUG-001 care team save without permission, BUG-002 cross-patient preference edits, BUG-003 PHI
before authorization, BUG-010/011 stored XSS). **Decided (§12):** fix the Critical and
High LEGACY rows as a separate, small change on this branch before the merge — each needs a
reproduction test first, which requires a restricted test user on the dev stack (not created
without approval) — and report them upstream.

---

## 11. Layout of the new app

```
dashboard/                       new top-level directory, own package.json (Node 22 is fine; it does not
                                 share OpenEMR's package.json or its Node >= 24 requirement)
  src/
    auth/        SMART launch, client, scopes
    fhir/        schemas (Zod) and view models, one file per resource; "active" rules live here
    format/      dates, ages, deceased text, units (R6)
    cards/       Card chrome (R5, R7, R9) and one component per card
    header/      PatientHeader
    app/         routing, error boundary, query client
  tests/         fixtures (recorded FHIR bundles), unit tests, parity harness
  e2e/           Playwright
```

---

## 12. Decisions

Rows 1-7 decided 2026-09-25; rows 8-9 on 2026-09-26.

| # | Decision | Outcome | ADR |
|---|---|---|---|
| 1 | Framework | React + TypeScript + Vite | [0001](../../docs/adr/0001-dashboard-react-typescript-vite.md) |
| 2 | Hosting | B: served by OpenEMR from `public/dashboard/` (A failed the 4.0 spike) | [0008](../../docs/adr/0008-dashboard-served-from-openemr.md), supersedes [0002](../../docs/adr/0002-dashboard-separate-static-hosting.md) |
| 3 | Extra section | Vitals | [0003](../../docs/adr/0003-dashboard-vitals-extra-section.md) |
| 4 | Fix the Critical/High LEGACY rows before merge | Yes, separate small change with reproduction tests | [0004](../../docs/adr/0004-fix-legacy-critical-high-before-merge.md) |
| 5 | Create a restricted test user on the dev stack to reproduce the Critical findings | Yes, dev stack only | [0005](../../docs/adr/0005-restricted-test-user-dev-stack.md) |
| 6 | Co-Pilot and Demo Data tabs | Links inside the SPA (see below) | [0006](../../docs/adr/0006-copilot-links-carry-fhir-patient-id.md) |
| 7 | Browser test tool | Playwright only, for end to end and the parity harness (§7) | [0007](../../docs/adr/0007-playwright-for-dashboard-browser-tests.md) |
| 8 | In-EMR entry point | The chart opens the new dashboard in place of the old cards, behind an admin setting (off by default). Deviates from "no backend changes" | [0009](../../docs/adr/0009-new-dashboard-in-the-chart.md) |
| 9 | FHIR API skips the user's ACL for patient-scoped tokens (API-11) | Accept as a constraint; the chart embeds the app only for users with `patients/med` and the issue ACLs; a characterization test records the standalone leak | [0010](../../docs/adr/0010-accept-fhir-acl-gap-guard-the-chart.md) |

### 12.1 Co-Pilot and Demo Data links

Today both tabs live in the chart's patient navbar (`PatientMenuEvent`, module `Bootstrap.php`)
and read the patient from the PHP session (`ActivePatient`). The SPA has neither the navbar nor
the session; its patient comes from the SMART launch as a FHIR id.

The SPA header gets two links. Rules:

- The link carries the patient's FHIR id (`?patient=<uuid>`), never the internal `pid`.
- The module page resolves the uuid to a `pid` and **refuses unless it equals the session
  patient**. The refusal names the mismatch and offers to open the chart for the SPA's patient;
  it never shows the session patient's data under the SPA's patient. The existing page with no
  `patient` parameter behaves as today.
- No OpenEMR session: the page shows OpenEMR's login, as any module page does. The SMART login
  does not create an interface session.
- Demo Data is linked only when the module reports `demoTools` on; the SPA reads that from a
  public, PHI-free flag, or the link is omitted.
- Tests first: matching uuid → page; mismatched uuid → refusal; unknown uuid → refusal; no
  session → login; no parameter → unchanged.

This is a change to our module, not to OpenEMR core. The brief's "no backend changes" is read as
OpenEMR's backend; the defense says so. Open for the Phase 4.0 spike: whether `patient.php` and
`demo.php` render correctly outside the tabs shell (they call `top.navigateTab` and
`top.restoreSession` where present).
