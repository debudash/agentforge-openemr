# 0002. Host the new dashboard as a separate static service

Status: superseded by [0008](0008-dashboard-served-from-openemr.md) (2026-09-25). Supersedes: none.

## Context

The brief says the backend is not touched. The built app is static files. It can be served by a
host of its own, or copied into OpenEMR's `public/` and served from the same origin (spec §4).

## Decision

A separate static service: the Vite dev server on `http://localhost:5173` locally, and a static
Railway service when deployed.

## Consequences

- Deploys independently of OpenEMR and shows the backend is untouched.
- Cross-origin: it depends on OpenEMR's CORS, which today reflects any origin and sends a malformed
  `Allow-Methods` header (CONST API-04). The app uses GET only, which works; same-origin hosting is
  the fallback if that changes.
- The OAuth client needs a redirect URI per host (local and Railway).
- A Railway deploy needs the owner's approval, like every other Railway change.
