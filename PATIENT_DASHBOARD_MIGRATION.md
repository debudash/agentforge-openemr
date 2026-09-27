# Patient dashboard migration

The patient dashboard's presentation layer, moved from server-rendered PHP to a React and
TypeScript app that reads OpenEMR's FHIR API. A doctor opens a patient in OpenEMR and gets the new
dashboard in the chart, in one click. The app is in `dashboard/`; OpenEMR serves the built files
from `public/dashboard/`.

Full engineering detail, every constraint and the evidence are in
[dashboard-modernization/](dashboard-modernization/05-migration-details.md). Decisions are ADRs
0001-0010 in [docs/adr/](docs/adr/).

## What was built

| Brief | Built |
|---|---|
| Login via OAuth2 / OpenID Connect | SMART on FHIR: authorization code with PKCE, an OpenID Connect ID token for the doctor, and read-only scopes for one patient. In the chart the doctor's OpenEMR sign-in is reused (single sign-on); the exchange still runs on every open. The app also runs on its own URL, which shows the full login screen: that is how the login is demonstrated. |
| Patient header: name, DOB, sex, MRN, active status | Name, MRN, DOB, age (or age at death), sex, status, and the signed-in doctor. |
| Allergies, Problem List, Medications, Prescriptions, Care Team | One card each, from `AllergyIntolerance`, `Condition`, `MedicationRequest` and `CareTeam`. Prescriptions keeps the legacy card's history: current first, then ended ones, with their status. |
| One more section | Vitals: the latest set (ADR 0003). |

The layout follows the legacy page, in the Bootstrap 4.6 that OpenEMR ships.

## How a doctor uses it

1. Opens a patient from the calendar, the finder or recent patients, as today.
2. The chart keeps its name bar and patient menu (History, Documents, Co-Pilot and the rest), and
   shows the new dashboard in place of the old cards, for that patient.
3. **Edit** on Allergies, Problems, Medications and Prescriptions opens the same OpenEMR editor the
   old card opens. Saving happens there, under OpenEMR's own permission checks; the app itself only
   reads.

An admin turns this on with one setting (below). Off, the chart shows the old cards.

## Why React, TypeScript and Vite

- **React escapes every value by default.** The legacy page runs Twig with escaping off for the
  whole application, and three templates forgot to escape (stored XSS). In the port, rendering HTML
  needs `dangerouslySetInnerHTML`, and lint fails the build on it.
- **TypeScript (strict), with each FHIR response parsed into a typed model at the boundary.** FHIR
  is optional fields everywhere; a missing field is a compile or parse error, not a blank at render
  time.
- **Vite builds static files.** No server runtime to secure, nothing between the browser and the
  API.
- **`fhirclient`**, the SMART reference client, does the OAuth. No hand-written OAuth.
- **Rejected:** Vue and Svelte (smaller SMART/FHIR ecosystem, no offsetting gain); modern Angular
  (shares little with OpenEMR's AngularJS, heavy for six cards); Next.js or any SSR (a second
  backend holding tokens and patient data); PHP with htmx (not a framework port).

## What moving off PHP gained

- **Authorization moved to where the data is.** The legacy page decided which cards to draw and
  its endpoints trusted that decision; most of the three Critical and eight High findings in our
  audit trace back to it. The port fetches nothing without a token, and the API authorizes every request.
- **Escaping by default,** which ends the XSS class above.
- **Separation.** One 2,080-line PHP file of SQL, authorization and HTML becomes a small app whose
  only input is API responses, on a published contract (FHIR R4 / US Core) instead of OpenEMR's
  tables.
- **Testable.** Every card is a function of parsed data, tested in seconds with no database or
  browser, plus end-to-end tests through the real login.

Ten design rules enforce these, each backed by a lint rule or a test
([details](dashboard-modernization/05-migration-details.md#what-moving-off-php-gained)).

## Tradeoffs

- **Coarser permissions from the API.** For this app's tokens the FHIR API checks only that the
  data belongs to the patient, not the user's own permissions. The chart therefore opens the app
  only for users allowed to see clinical data (ADR 0010); everyone else gets the old cards.
- **Served by OpenEMR.** OpenEMR's API cannot be called from another web origin, so the app is
  served from OpenEMR's own `public/` folder (ADR 0008). It still reads only through the API.
- **What FHIR does not carry.** Status comes from the deceased fields, because OpenEMR reports every
  patient as active. Empty lists read "No allergies recorded" or "None" rather than the legacy
  wording. A care team member marked inactive is still listed.
- **A Node toolchain** where there was none.

## The one change to OpenEMR

The brief says the backend is not touched. To put the new dashboard in the doctor's workflow, we
changed one page and added two settings (ADR 0009). This is a deliberate deviation.

| File | Change |
|---|---|
| `library/globals.inc.php` | Admin > Globals > Appearance: `patient_dashboard_renderer` (old cards, the default, or the SMART app) and the app's client ID. |
| `interface/patient_file/summary/demographics.php` | With the app selected: everything above the cards stays, and the card area becomes the app, launched for the patient being opened. Edit buttons open the legacy editors through this page, which builds every URL itself. |

- **Why this page:** every way of opening a patient loads it, so one change covers them all.
- **Rollback:** one setting. Off, the page is exactly as before.
- **Trust:** the admin marks the app as trusted, which skips the second login and consent screen.
  That is an admin decision for the clinic's own app.

Separately, the audit found security bugs in the old dashboard itself: care team and preference
writes without permission, patient data sent before the permission check, and stored XSS. They are
fixed in the old page, which stays in the product, each reproduced by a failing test first
([details](dashboard-modernization/05-migration-details.md#legacy-fixes)).

## Parity

A harness renders the old and new dashboards for every patient on the dev stack, as the same
doctor, and compares each card: same items, same order, same empty state. Any difference without a
documented reason fails the run. On all 50 patients there was none unexplained. The differences:

- empty-list wording (FHIR does not carry the flag the old card used);
- BMI shown as recorded, not rounded; "23 months", not "23 month";
- care team names as "Given Family";
- one flagged: the inactive care team member above.

Prescriptions first differed (active only) and now matches the old card's history: 140 of 140
items on the 10 patients with the most prescriptions
([report](dashboard-modernization/04-evidence/prescription-history/README.md)).

## Known limits

- **The login demo URL.** Opened on its own, outside the chart, the app is not covered by the chart's
  permission check, so a user with demographics access but no clinical access could read clinical
  data. The fix belongs in OpenEMR's API; a test records the gap and will fail once it is fixed.
  Use that URL for the login demo only.
- **Not deployed** to the public Railway instance yet.

## Running it

```bash
cd dashboard
npm ci
npm run build        # writes ../public/dashboard/, served by OpenEMR
npm run lint && npm run typecheck && npm test   # what CI runs
npm run e2e          # local, against the dev stack
```

One-time setup (the OAuth client and the admin setting) is in
[the detail file](dashboard-modernization/05-migration-details.md#deviation-from-the-brief-one-openemr-change).
