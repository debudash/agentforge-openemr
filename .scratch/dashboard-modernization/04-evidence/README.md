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
