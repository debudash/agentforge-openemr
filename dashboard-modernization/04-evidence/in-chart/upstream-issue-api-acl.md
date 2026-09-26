# Draft upstream issue (not filed)

**Title:** FHIR API skips the user's ACL when a practitioner's token has `patient/` scopes

## Summary

When a provider signs in to a SMART app that holds `patient/<Resource>.rs` scopes, the FHIR API
does not check the provider's gacl permissions. A user with `patients/demo` but without
`patients/med` can read Condition, AllergyIntolerance, MedicationRequest and Observation for the
patient in context. The same user cannot see these in the patient dashboard.

Public clients can hold only `patient/` scopes (registration rejects `user/` scopes for them), so
every browser-based SMART app used by providers is affected.

## Where

- `src/Common/Http/HttpRestRouteHandler.php` L62-67: if the token has a `patient` scope context
  for the route's resource, `setPatientRequest(true)`, whatever the user's role.
- `src/RestControllers/FHIR/FhirGenericRestController.php` L93-102: for a patient request, the
  route's `addAclRestrictions()` checks are skipped; only the patient binding is applied.

## Steps to reproduce

1. Create a user in an ACL group with `patients/demo` view only (no `patients/med`).
2. Register a public SMART client with `openid fhirUser launch/patient patient/Condition.rs`
   (enable it).
3. Sign in to the app as that user, pick a patient with problems, approve.
4. `GET /apis/default/fhir/Condition?patient=<uuid>` with the token.

Expected: 403, as for the dashboard's Medical Problems card. Actual: 200 with the problem list.

Reproduced on 8.2.0-dev, 2026-09-26. The same holds for AllergyIntolerance, MedicationRequest and
Observation.

## Suggested fix

For a patient request whose token belongs to a `users`-role user (not a patient portal user),
still run the route's gacl checks, in addition to the patient binding. Patient-role tokens keep
today's behaviour (the patient binding is their authorization).

## Related

The FHIR routes also do not apply per-issue-type ACLs (`aclCheckIssue`) or squads, which the
dashboard does. That is a coarser-granularity issue, separate from this one.
