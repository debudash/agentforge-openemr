# Patient dashboard modernization

Additional Week 2 deliverable: port the patient dashboard's presentation layer to a modern
framework over OpenEMR's REST/FHIR API (brief: `requirements/…Modernize the Patient Dashboard.pdf`).
Built on branch `dashboard-modernization` from `week2-baseline`, merged into `week2` for delivery.

Each phase produces an artifact the next one leans on.

| Phase | Artifact | Status |
|---|---|---|
| 0. Entry point and dependency tree | [00-tree.md](00-tree.md) | done |
| 1. Per-file audit | [01-audit/](01-audit/) — 51 files, plus [the API the port depends on](01-audit/_api-port-dependencies.md) | done |
| 2. Bug catalog | [02-bug-catalog.md](02-bug-catalog.md) — 145 findings in 104 rows | done |
| 3. Migration spec | [03-migration-spec.md](03-migration-spec.md) | draft; 5 open decisions in §12 |
| 4. Rewrite | `dashboard/` and `PATIENT_DASHBOARD_MIGRATION.md` | not started |

Audit file names are the source path with `/` replaced by `-`, e.g.
`src-Patient-Cards-CareTeamViewCard.php.md`.

The catalog is generated from the audit tables: `python .scratch/dashboard-modernization/tools/build_catalog.py`.
It fails if any audit finding is missing from its triage map. `tools/check_tables.py` checks that
every markdown table row has the right number of cells.
