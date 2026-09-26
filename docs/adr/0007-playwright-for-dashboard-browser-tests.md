# 0007. Playwright for the dashboard's browser tests, not the Selenium container

Status: accepted (2026-09-25). Supersedes: none.

## Context

The spec planned Playwright for the new app's end-to-end tests and the dev stack's Selenium
container for the parity harness, which renders the legacy and new dashboards for the same
patient and compares them. The Selenium browser runs inside Docker, where `localhost` is its own
container. OpenEMR's OAuth address (`site_addr_oath`) is `https://localhost:9300` and the new app
runs on the host at `localhost:5173`, so a SMART login cannot complete from there.

## Decision

Playwright, running on the host, for both the end-to-end tests and the parity harness.

## Consequences

- One browser tool, in the same TypeScript as the app; the harness drives both dashboards in one
  test.
- The Selenium container stays in the stack for OpenEMR's own E2E suite and browser debugging.
  Nothing of ours used it.
- The GitLab pipeline has no OpenEMR stack, so it runs only the unit tests. The harness and
  end-to-end tests run locally, and their reports are committed.
- The legacy page is opened through the tabs shell, because `demographics.php` calls
  `parent.left_nav` when loaded on its own. Tests set `ignoreHTTPSErrors` for the stack's
  self-signed certificate.
