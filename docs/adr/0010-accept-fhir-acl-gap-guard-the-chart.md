# 0010. Accept the FHIR API's ACL gap for patient-scoped tokens; guard the chart

Status: accepted (2026-09-26). Supersedes: none.

## Context

The ADR 0009 tests found that a user who holds `patients/demo` but not `patients/med` reads the
clinical record through the new dashboard: problems, allergies, medications, vitals, all 200.
The legacy cards hide these from that user. The cause is in OpenEMR's API core, not the port:

- `src/Common/Http/HttpRestRouteHandler.php` L62-67 marks a request as a patient request when the
  token holds a `patient/<Resource>` scope for the route's resource, whatever the user's role.
- `src/RestControllers/FHIR/FhirGenericRestController.php` L93-102 then skips the route's gacl
  checks (`addAclRestrictions("patients", "med")`) and applies only the patient binding.
- A public client can hold only `patient/` scopes (API-06), so every token the app can get skips
  the check.

The standalone launch (Phase 4) leaks the same way; the ADR 0009 chart launch would make it one
click. Recorded as API-11 / BUG-110. Evidence: `04-evidence/in-chart/finding-no-med-leak.txt`.

The options were: (A) guard the launch point in the chart; (B) fix the API core; (C) accept the
gap as a documented constraint. B changes OpenEMR's API authorization, which the brief rules out.

## Decision

A and C.

- **A.** `demographics.php` embeds the SMART app only for a user who holds `patients/med` and the
  allergy, medical-problem and medication issue ACLs (`aclCheckIssue`), the checks the legacy
  clinical cards use. Anyone else gets the legacy cards, which apply their own per-card checks.
- **C.** API-11 is an accepted constraint (CONST) in the catalog and the defense. A
  characterization test (`dashboard/e2e/known-limits.spec.ts`) proves the leak exists today and
  fails once the API is fixed.

## Consequences

- In the chart, a user without `patients/med` never gets a token: no launch, no OAuth, no FHIR
  request (tested).
- The standalone URL (`/public/dashboard/`) still leaks the clinical record to a user with
  `patients/demo` but not `patients/med`. A browser client cannot enforce what the server does
  not. The app's About panel and the defense say so.
- The real fix is server-side (B): apply the route's gacl checks to `users`-role tokens on patient
  requests. An upstream issue is drafted in `04-evidence/in-chart/upstream-issue-api-acl.md`, not
  filed.
- When upstream fixes it, the characterization test fails; then remove the test, the CONST row
  and, optionally, the chart guard.
- The guard adds one rule to the ADR 0009 change in `demographics.php`, still generic: any SMART
  app used as the dashboard body inherits it.
