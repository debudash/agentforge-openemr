# API surface the port depends on

Not dashboard files. The brief says the new dashboard consumes OpenEMR's existing REST and FHIR
APIs and does not touch the backend, so how those APIs behave is a constraint on the port. These
were checked against the code at `week2-baseline`; each point cites its source.

## Resources available (FHIR R4, US Core 3.1.0)

`apis/routes/_rest_routes_fhir_r4_us_core_3_1_0.inc.php` exposes GET for, among others:
`Patient`, `AllergyIntolerance`, `Condition`, `MedicationRequest`, `CareTeam`, `Encounter`,
`Observation`, `Immunization`, `Appointment`, `DiagnosticReport`, `Coverage`, `Practitioner`,
`Organization`, `RelatedPerson`, plus `metadata`. Everything the brief requires has a resource.

## How dashboard concepts map

| Dashboard | FHIR | Evidence |
|---|---|---|
| MRN (pubpid) | `Patient.identifier` with type `PT` (system v2-0203) | `FhirPatientService.php` L552-566 |
| Medication list ("Medications" card) | `MedicationRequest` with `intent=plan` | `PrescriptionService.php` L203-213 (lists_medication rows get intent `plan`) |
| Prescriptions | `MedicationRequest` with `intent=order` | `PrescriptionService.php` L93-94, L156-157 |
| Problem list | `Condition` (problem-list-item) | `FhirConditionService` |
| Allergies | `AllergyIntolerance` | route L73-84 |
| Care team | `CareTeam?patient=` | route list |

## Findings

| ID | Sev | Where | Finding |
|---|---|---|---|
| API-01 | High | FHIR routes, e.g. L73-84 (AllergyIntolerance), L167-176 (Condition) | **The API's authorization is coarser than the dashboard's.** User requests are checked against `patients/med` only. The dashboard also checks each issue type (`aclCheckIssue('allergy'\|'medical_problem'\|'medication')`) and the patient's squad. Neither exists in the API layer (`grep` for `squad` and `aclCheckIssue` in `src/Services/FHIR`, `src/RestControllers`, `apis`: no hits). A FHIR-based dashboard will show data the current page hides from users restricted by issue type or squad, and a browser client cannot enforce restrictions the server does not. |
| API-02 | Medium | `FhirPatientService.php` L212 | **`Patient.active` is always `true`.** The brief's "active status" cannot come from this field; the spec defines what the header shows instead. |
| API-03 | Medium | list_touch vs FHIR | **"No Known Allergies" vs "Nothing Recorded" is not in the API.** The dashboard distinguishes them with `getListTouch()`; FHIR returns an empty bundle either way unless NKA was recorded as an allergy entry. |
| API-04 | Low | `src/RestControllers/Subscriber/CORSListener.php` L57, L66-74 | **CORS reflects any `Origin`** (with `Allow-Credentials: true` on preflight). This is what lets a separately hosted dashboard call the API. On L68 a comma where `=>` belongs means `Access-Control-Allow-Methods` is never set correctly; GET still works, as a CORS-safelisted method. |
| API-05 | Low | `ClientRepository.php` L56 | **Public clients are supported** (`is_confidential` = 0 when no secret). A browser app can use the authorization-code flow with PKCE, which league/oauth2-server requires for public clients. To be proven end to end as the first rewrite step. |
