# Spike: EHR launch from the legacy chart

Run 2026-09-26 on the local stack. Question: can a doctor open a SMART app from inside the chart,
for the patient on screen, with OAuth2/OIDC underneath and no OpenEMR code change? **Yes.**

## Setup (configuration only)

- A throwaway public client, registered by dynamic registration with `scope` including `launch`
  and `initiate_login_uri` set to the app's launch page.
- It registered **disabled**; an admin enables it (Admin > System > API Clients). Done here in the
  database as the same change.
- Two throwaway pages: `launch.html` (receives `iss` and `launch`, calls
  `FHIR.oauth2.authorize`) and `index.html` (`FHIR.oauth2.ready`, prints the token, patient, ID
  token and one search). `fhirclient` 2.6.3 browser bundle, PKCE required.

Driver: `spike-ehr-launch.mjs`. doctor1 signs into OpenEMR, opens patient 1 in the chart, expands
the "SMART Enabled Apps" card (collapsed by default) and clicks **Launch**. The app opens in a
full-screen dialog over the chart (`ehr-*-3-app.png`).

## Results

| | Run A: per-app skip flag off | Run B: per-app skip flag on |
|---|---|---|
| Login screen | shown (`ehr-A-2-login.png`) | **not shown** |
| Consent screen | shown (`ehr-A-2-consent.png`) | **not shown** |
| Patient picker | not shown: the patient comes from the chart | not shown |
| Token | code + PKCE, `openid fhirUser launch patient/*.rs` | same |
| Patient in context | pid 1 (`a2bf78a3-…`), the chart's patient | same |
| ID token | yes; `fhirUser` = doctor1's Practitioner | same |
| Data | `Patient` read and `AllergyIntolerance` search, 200 | same |

Navigation in Run B: `ehr-launch-client.php` → `launch.html` → `/oauth2/default/authorize` →
`index.html`. One click.

## How OpenEMR decides

`AuthorizationController::oauthAuthorizationFlow` (L593-597): with a `launch` parameter,
`shouldSkipAuthorizationFlow()` (L1653) requires the global `oauth_ehr_launch_authorization_flow_skip`
= 1 **and** the client's `skip_ehr_launch_authorization_flow` = 1. Only then does
`getLoggedInCoreUserUuid()` reuse the signed-in user from the `OpenEMR` session cookie, and the
scopes are approved without a consent screen. Login skip and consent skip are one switch. The
global was already 1 on this stack.

## Limits found

- The launch point is the chart's "SMART Enabled Apps" card only. `SMARTLaunchToken` defines an
  appointment intent, but nothing in the calendar UI uses it.
- The card starts collapsed.
- A new client starts disabled.
- The skip flag trusts the app with every scope it registered; it is an admin decision per client.

## Cleanup

Deleted: the client, 2 `api_token`, 2 `api_refresh_token`, 1 `oauth_trusted_user` row; the
pages under `public/ehr-launch-spike/`. The global was not changed.
