# Phase 4.0 spike: SMART standalone launch, public client + PKCE

Run 2026-09-25 against the local stack (`docker/development-easy`, OpenEMR 8.2.0-dev, HEAD
`0c3db5b`). Scripts are in `spike/`; raw output in `spike-4.0-run.txt` (cross-origin) and
`spike-4.0-same-origin.txt` (same-origin).

## Result

PKCE and the public client work. The cross-origin data calls do not: every FHIR request from
`http://localhost:5173` fails its CORS preflight. ADR 0002 (separate static host) cannot work on
this OpenEMR without a core change. Phase 4 stopped here, as the brief for the rewrite requires.

| Step | Result |
|---|---|
| Dynamic registration, public client | Works. `application_type` other than `private` gives a public client (`is_confidential=0`, `is_enabled=1`). `token_endpoint_auth_method: none` is rejected (`AuthorizationController.php` L274); omitting it is what makes the client public. |
| `user/` scopes on a public client | Rejected at registration: "system and user scopes are only allowed for confidential clients" (`AuthorizationController.php` L325-330). The spec's §4 scope list (`user/*.rs`) cannot be used. |
| `patient/` scopes, provider login | Works. doctor1 signs in with "OpenEMR Login", picks the patient, approves scopes. The token carries `launch/patient` context and `patient/*.rs`; the API binds requests to that patient (`BearerTokenAuthorizationStrategy.php` L259-265, `AuthorizationListener.php` L143-150). |
| Authorization code + PKCE S256 | Works (`fhirclient` 2.6.3, `pkceMode: "required"`); token POST is a CORS simple request, so it succeeds cross-origin. |
| FHIR GET from the browser, cross-origin | **Fails.** `Authorization: Bearer` is not a safelisted header, so Chrome sends a preflight `OPTIONS`. OpenEMR answers `404 Route not found` with no `Access-Control-Allow-Headers`. Console: "Response to preflight request doesn't pass access control check: It does not have HTTP ok status." |
| Same token, no browser | 200 for `Patient`, `AllergyIntolerance`, `Condition` (73), `MedicationRequest` (8), `CareTeam` (0), `Observation?category=vital-signs` (15). The token and scopes are good; only the preflight fails. |
| Same page served same-origin (`https://localhost:9300/public/dashboard-spike/`) | **Works end to end in the browser**: token, `Patient` read, all five searches. The spike files were removed from `public/` afterwards. |

## Why the preflight fails

`CORSListener::onKernelRequest` answers `OPTIONS` itself, but it is registered at priority 25
(`src/RestControllers/Subscriber/CORSListener.php` L20). Symfony runs higher priorities first:
`AuthorizationListener` (50) and `RoutesExtensionListener` (40) run before it, and the router has no
`OPTIONS` routes, so the request ends as a 404 before CORS sees it. The catalog's API-04 finding
(the `,` for `=>` on L69) is real but secondary: `Allow-Methods` is not needed for GET, while
`Allow-Headers: authorization` is, and that response is never produced.

So API-04's "GET still works, as a CORS-safelisted method" holds only for requests without an
`Authorization` header. Every authenticated FHIR call needs a preflight.

## Options for the owner

| Option | What changes | Cost |
|---|---|---|
| A. Same-origin hosting (ADR 0002's named fallback, spec §4 option B) | Build output served by OpenEMR, e.g. `public/dashboard/`; redirect URI `https://localhost:9300/public/dashboard/`. Local dev: `vite build --watch` into the bind mount, or Vite dev only for Vitest/MSW work. | Supersedes ADR 0002. The app ships inside the OpenEMR image, which blurs "not touching the backend" (no backend code changes, but OpenEMR serves the files). Proven by this spike. |
| B. Fix `CORSListener` in core | Raise its request priority above 50 (and fix L69). About three lines, upstreamable. | A core change outside ADR 0004's scope. Keeps ADR 0002. Also worth pairing with origin restriction, since the listener reflects any origin with `Allow-Credentials: true`. |
| C. Reverse proxy on the static host | The static service proxies `/apis/` to OpenEMR so the browser sees one origin. | `aud` must still be OpenEMR's FHIR URL (`CustomAuthCodeGrant.php` L80-103), so `fhirclient`'s server URL must be overridden after launch. Puts a hop holding bearer tokens between browser and API, which spec §3 rejected for SSR. Not tested. |

Recommendation: A for this deliverable (no OpenEMR code change, proven), with B filed upstream
alongside the other API findings.

## Other spike answers

- **Co-Pilot pages outside the tabs shell.** With doctor1 signed in and `set_pid=1`,
  `patient.php` and `demo.php` opened as top-level pages render fully, with no page errors or
  console errors. Their `top.app_view_model` and `top.document` reads are in `try/catch`, so the
  stale-patient banner stays hidden (the page claims nothing when it cannot read the shell).
  Screenshots: `spike/patient.php.png`, `spike/demo.php.png`.
- **Scopes to use** (pending the hosting decision): `openid fhirUser launch/patient
  patient/Patient.rs patient/AllergyIntolerance.rs patient/Condition.rs patient/MedicationRequest.rs
  patient/Medication.rs patient/CareTeam.rs patient/Practitioner.rs patient/RelatedPerson.rs
  patient/Observation.rs`. Patient-bound tokens are narrower than the spec's `user/` scopes (one
  patient per token), which suits R8.
- **`fhirclient` version.** 3.0.0 (released 2026-09-18) ships type declarations that import a
  missing `types/types.d.ts`; 2.6.3 is used. 2.6.3 pulls `isomorphic-webcrypto`, whose optional
  Expo dependencies bring 9 moderate `npm audit` advisories (`uuid` via `xcode`); none is in the
  browser bundle, but it needs a note or an override.

## Left on the stack

- OAuth client `BC1OPvb0PJttDjSCR5GeirM0D0oD8a8P989Pm0N8ZJU` ("Patient Dashboard (local)",
  public, redirect `http://localhost:5173/`). Remove with
  `DELETE FROM oauth_clients WHERE client_id = 'BC1OPvb0PJttDjSCR5GeirM0D0oD8a8P989Pm0N8ZJU';`
  or disable it in Admin > System > API Clients. The same-origin spike's second client was
  deleted. Access and refresh tokens issued to doctor1 during the spike expire on their own.
- doctor1's interface session had `set_pid=1` applied once (recent-patients list write).
