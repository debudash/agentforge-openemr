# 0008. Serve the new dashboard from OpenEMR, same origin

Status: accepted (2026-09-25). Supersedes: [0002](0002-dashboard-separate-static-hosting.md).

## Context

The Phase 4.0 spike (`.scratch/dashboard-modernization/04-evidence/spike-4.0.md`) proved SMART
login with a public client and PKCE, but every FHIR call from a separate origin fails. A bearer
token forces a CORS preflight, and OpenEMR answers `OPTIONS` with `404 Route not found`:
`CORSListener` runs at priority 25, after authorization (50) and routing (40)
(`src/RestControllers/Subscriber/CORSListener.php` L20). The same app served from
`https://localhost:9300/public/` worked end to end. The alternatives were a core CORS fix, which
the brief rules out, and a reverse proxy, which adds a hop holding bearer tokens (spec §3).

## Decision

The built app is served by OpenEMR from `public/dashboard/`, at
`https://<openemr>/public/dashboard/`, which is also its OAuth redirect URI.

## Consequences

- No OpenEMR code change. The app still reads data only through the FHIR API with its own token;
  OpenEMR serves its files and nothing else.
- Local development runs `vite build --watch` into `public/dashboard/` (bind-mounted, so changes
  are live). The Vite dev server is not used against the API, because its origin would be
  cross-origin again. Unit tests use MSW and need no server.
- Build output in `public/dashboard/` is gitignored. How the Railway image gets it (a Node build
  stage or committed output) is decided at the deploy step, with the owner's approval.
- Scopes are `patient/*.rs`: OpenEMR refuses `user/` scopes for public clients
  (`AuthorizationController.php` L325-330). Each token is bound to the one patient chosen at login.
- The CORS defect is reported upstream: preflight never answered, a malformed `Allow-Methods`
  header, and any origin reflected with credentials.
