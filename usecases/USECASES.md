# Sample-data use cases

Checks that the local OpenEMR stack, loaded with Synthea synthetic patients,
supports the questions a clinician (or a clinical agent) would ask. Each use
case runs through the same path an agent would use: OAuth2 password grant →
FHIR R4 / REST API → service layer → MariaDB.

All data is synthetic (Synthea). Never point these tests at a system with real
patient data.

| ID | Use case | Question it answers | API path | Pass condition |
|----|----------|---------------------|----------|----------------|
| UC0 | Dataset loaded | Is the sample data actually there? | SQL | ≥ 50 patients, every patient has a UUID, encounters/problems/meds/vitals all non-empty |
| UC1 | Find a patient | "Pull up Jane Doe." | `GET /fhir/Patient?family=&given=` | The expected patient (same name and birth date) is in the results, with a UUID |
| UC2 | Problem list | "What conditions does she have?" | `GET /fhir/Condition?patient=` | ≥ 1 Condition, each coded and linked to that patient |
| UC3 | Medications | "What is she taking?" | `GET /fhir/MedicationRequest?patient=` | ≥ 1 MedicationRequest linked to that patient |
| UC4 | Allergies | "Any allergies?" | `GET /fhir/AllergyIntolerance?patient=` | Valid Bundle for that patient (empty is allowed) |
| UC5 | Latest vitals | "What were her last vitals?" | `GET /fhir/Observation?patient=&category=vital-signs` | Every vital-signs Observation is dated and has a value, components, a data-absent reason, or (for panels) members; at least one carries a measured value |
| UC6 | Visit history | "When was she last seen?" | `GET /fhir/Encounter?patient=` | ≥ 1 Encounter with a start date |
| UC7 | Immunizations | "Is she up to date on shots?" | `GET /fhir/Immunization?patient=` | Valid Bundle for that patient |
| UC8 | One source of truth | Do REST and FHIR agree? | `GET /api/patient/:puuid` vs `GET /fhir/Patient/:id` | Same UUID, name and birth date |
| UC9 | No token, no data | Is anonymous access blocked? | `GET /fhir/Patient` without a token | 401 |
| UC10 | Least privilege | Does a narrow token stay narrow? | Token with only `user/Patient.read`, then `GET /fhir/Condition` | Denied (401/403), while `GET /fhir/Patient` still works |
| UC11 | Clinician UI | Can a person log in and reach the app? | `POST /interface/main/main_screen.php` | Redirects to `interface/main/tabs/main.php` |

## Running

```powershell
cd D:\Dev\OpenEMRAgent\usecases
.venv\Scripts\python -m pytest
```

Requires the `docker/development-easy` stack to be running. Defaults target
`https://localhost:9300` with `admin` / `pass`; override with
`OPENEMR_BASE_URL`, `OE_USER`, `OE_PASS`.

### Against the Railway deployment

The suite needs database access (to enable its throwaway OAuth client, and for the
UC0 dataset checks). Set `OE_DB_VIA=railway` and it runs those queries through
`railway ssh` instead of `docker compose exec`; see `deploy/railway/README.md`.

```powershell
$env:OPENEMR_BASE_URL = "https://<app>.up.railway.app"
$env:OE_PASS   = "<admin password>"      # OpenEMR login
$env:OE_DB_VIA = "railway"
$env:OE_DB_PASS = "<openemr db user password>"
.venv\Scripts\python -m pytest
```

Requires the Railway CLI, logged in, with the project linked (run once from the
repo root: `railway link`). Each query costs an SSH round trip, so the suite is
slower than against the local stack.

The suite registers a throwaway OAuth client, enables it directly in the
database (new clients start disabled), and deletes it and its tokens when the
run ends.
