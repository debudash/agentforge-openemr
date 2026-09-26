# 04 — Evidence

Phase 4 (the rewrite) outputs, for the defense (`PATIENT_DASHBOARD_MIGRATION.md`) and the review.
Everything was run against the local `docker/development-easy` stack; nothing touched Railway.

| File | What it shows |
|---|---|
| `spike-4.0.md`, `spike-4.0-*.txt`, `spike/` | 4.0: PKCE and the public client work; cross-origin FHIR calls fail their CORS preflight; same-origin works (ADR 0008) |
| `before-usecases.txt`, `before-gate.txt` | The existing suites before any Phase 4 change |
| `after-usecases.txt`, `after-gate.txt` | The same suites after |
| `parity/parity-report.md` (+ `.json`, `pids/`) | The parity harness over every patient on the stack |
| `red-legacy-security.txt`, `green-legacy-security.txt` | ADR 0004 reproductions (Playwright, as the restricted users): failing before the fix, passing after |
| `red-legacy-twig.txt`, `green-legacy-twig.txt` | BUG-009 and BUG-011 template tests, before and after |
| `red-dashboard-links.txt`, `green-dashboard-links.txt` | ADR 0006 refusal path (`usecases/test_uc_dashboard_links.py`), before and after |
| `e2e-dashboard.txt` | End to end through real SMART login: header, cards, GET-only traffic, CSP console, axe, sign-out, Co-Pilot link |
| `unit-test-mutations.txt` | Each rule-carrying line broken on purpose; the named test or lint must fail |
| `ci-dashboard-job-local.txt` | The proposed `dashboard` CI job run in `node:22-alpine` from a clean checkout |
| `phpunit-isolated.txt` | PHPUnit isolated suite, before and after |
| `phpstan-changed-files.txt`, `phpcs-changed-files.txt` | PHPStan level 10 (full codebase, filtered to changed files) and PHPCS on changed files |
| `npm-audit-reach.txt` | Which packages are in the shipped bundle; the audit advisories' reach |
| `reviews.md` | Security review and code review findings and what happened to each |
| `stack-changes.md` | Everything created on the local stack, and how to remove it |
| `spike-ehr/` | The EHR-launch spike: a SMART app launched from the chart for its patient, no login or consent when the client is trusted |
| `in-chart/` | ADR 0009 and 0010: the new dashboard in the chart, behind a setting, guarded by `patients/med` (below) |

### `in-chart/`

| File | What it shows |
|---|---|
| `before-*.txt`, `after-*.txt` | Usecases (94/94), stage 2 gate (74/74), PHPUnit isolated (3491, unchanged), dashboard lint/typecheck/Vitest (57 → 73) before and after |
| `e2e-in-chart.txt` | The in-chart suite and the known-limit test: calendar, finder, fast switch, launch race, no patients/demo, no patients/med, no issue ACL, setting on legacy, no client id (10 of 10) |
| `in-chart-calendar.png`, `in-chart-finder.png`, `in-chart-no-med.png` | The chart with the app; the legacy page for a user without patients/med |
| `green-legacy-security-setting-legacy.txt`, `parity-setting-legacy.txt` | Legacy security (15/15) and parity (pids 1, 3, 5) with the setting switched to legacy by the tests |
| `e2e-dashboard-standalone.txt` | The Phase 4 standalone e2e after the change (4/4) |
| `finding-no-med-leak.txt` | API-11: a patient/-scoped token skips the user's ACL (reproduced standalone and in the chart) |
| `upstream-issue-api-acl.md` | Draft upstream issue for API-11 (not filed) |
| `catalog-regeneration.txt` | API-11 appended as BUG-110; BUG-001 to BUG-109 and every cited id unchanged |
| `unit-test-mutations.txt` | Five rule lines broken on purpose (wrong patient, iss, Sign out, the guard, one issue ACL); each fails its test |
| `phpstan-phpcs.txt` | PHPStan level 10 (full codebase) and PHPCS on the changed PHP files |
| `reviews.md` | Security review and code review of this change, and what happened to each finding |
| `commit-split/` | Patches and steps to stage the Phase 4 commits and this change separately |
