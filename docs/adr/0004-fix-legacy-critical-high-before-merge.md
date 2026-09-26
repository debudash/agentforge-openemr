# 0004. Fix the legacy dashboard's Critical and High bugs before merge

Status: accepted (2026-09-25). Supersedes: none.

## Context

The legacy PHP dashboard stays in the product next to the port. The audit found 3 Critical and 8
High defects in it: a care team saved without permission, cross-patient preference edits, PHI sent
before the authorization check, fragments with no authorization, and three stored-XSS sinks
(`02-bug-catalog.md`, LEGACY rows). All were found by reading the code; none has been reproduced.

## Decision

Fix the Critical and High LEGACY rows on the `dashboard-modernization` branch, as a change separate
from the port, before it merges into `week2`. Each fix starts with a failing test that reproduces
the bug. Report them upstream.

## Consequences

- Live security defects are closed rather than only documented.
- Reproduction needs a restricted user (ADR 0005).
- The fixes change OpenEMR code, not just the port, and must pass the repo's PHPStan level 10,
  PHPCS and the existing suites.
- Medium and Low LEGACY rows stay in the catalog as deferred.
