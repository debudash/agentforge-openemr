# Reviews of the ADR 0009 + ADR 0010 change

Scope: the in-chart change only, as a diff against the Phase 4 state of each file (the Phase 4
work has its own reviews in `../reviews.md`). Files: `library/globals.inc.php`, the three
`demographics.php` hunks, `dashboard/src/auth/smart.ts`, `src/app/App.tsx`,
`src/app/Dashboard.tsx` (About text), `src/header/PatientHeader.tsx`, the new tests and helpers,
and the two legacy specs' setup.

## Security review (`security-review` skill)

Run inline on the diff: it is small and was read in full. The skill's parallel sub-tasks were not
used.

| # | Finding | Confidence | Disposition |
|---|---|---|---|
| SR1 | A `patient/`-scoped token skips the user's ACL in the FHIR API (`HttpRestRouteHandler.php` L62-67, `FhirGenericRestController.php` L93-102). `dash-demoview` (patients/demo only) reads the clinical record: standalone (Phase 4) and, before the guard, in the chart in one click. Not introduced by this change. | 9 (reproduced) | **Guarded and accepted (ADR 0010).** The chart embeds the app only with patients/med and the three issue ACLs (tests 6 and 7; mutations M4, M5). Catalog API-11 / BUG-110 (CONST). `e2e/known-limits.spec.ts` proves the standalone leak. Upstream draft: `upstream-issue-api-acl.md`. |

Checked and held:
- The iframe `src` and `data-fhir-patient` are `attr()`-escaped. The URL is built with `http_build_query` from an admin global, the session CSRF token and a constant intent.
- The frame has `referrerpolicy="no-referrer"`.
- The `iss` is pinned to the app's own origin before any request (mutation M2).
- A token for any patient other than the chart's is refused (mutation M1; e2e race test).
- `frameElement` is null to a cross-origin parent, so a foreign page cannot declare a patient.
- The skip flag needs both the global and the per-client flag, and it applies only to requests that carry `launch`.

## Code review (`mattpocock-skills:code-review` against `week2-baseline`)

Two parallel reviewers ran on the scoped diff: Standards (CLAUDE.md, rules R1-R10 and the Fowler
smell baseline) and Spec (ADRs 0009 and 0010, the deviation section, the brief).

### Standards

No hard violation.

| # | Finding | Kind | Disposition |
|---|---|---|---|
| CS1 | `'legacy'` / `'smart_app'` is a closed, persisted set compared as a string (Enums over constants) | Soft | **Recorded.** A backed enum means a new `src/` file for a two-value select. Every other select global in `globals.inc.php` is a string map. The comparison fails closed: anything but `smart_app` shows the cards. |
| CS2 | `getUuid((string) $requestedPid)` casts (Narrow, don't cast) | Soft | **Kept.** The value is already narrowed by `is_int`, the cast is lossless, and `getUuid(string $pid)` needs a string. |
| CS3 | Two fully qualified class names inline where the file uses `use` | Style | **Kept on purpose.** A `use` line would land in the Phase 4 `use` hunk (L57), so the ADR 0009 hunks could not be staged apart from Phase 4. |
| CS4 | `Uuid::fromBytes()->toString()` duplicates `UuidRegistry::uuidToString()` | Smell | **Fixed.** Now `UuidRegistry::uuidToString()`. |
| CS5 | The `inChart` branch recurs five times across `App.tsx` and `PatientHeader.tsx` | Smell | **Recorded.** Five one-line branches in two components; a presentation map would add more than it removes. |
| CS6 | Optional `ehrLaunch` / `startEhr` / `inChart` in `AppDeps`, and the fallback they force | Smell | **Kept.** The existing tests build `AppDeps` without them; making them required changes every fixture. The fallback fails closed ("failed"). |
| CS7 | The `navigateTab` evaluate block appears twice in `in-chart.spec.ts` | Smell | **Fixed.** `openShellTab()` in `e2e/support/chart.ts`. |
| CS8 | The three-line `useRenderer` setup is repeated in three specs | Smell | **Recorded.** Kept explicit so each file shows what it switches; `in-chart.spec.ts` also uses `set`/`restore` inside a test. |
| CS9 | Test helpers build SQL by interpolation | Smell | **Recorded.** Test-only, and every value is a constant in the test. |

### Spec

| # | Finding | Disposition |
|---|---|---|
| SP1 | The issue-ACL half of the guard was untested | **Fixed.** New test 7: the allergy issue type is restricted to `admin/super`; doctor1 gets the cards and no app, and the ACO is restored. Mutation M5: removing the allergy check fails it. |
| SP2 | The fast-switch burst asserts only the end state | **Recorded.** Every settled open is asserted, and the race test covers the token side: a launch built for another patient is refused. Nothing checks mid-burst frames that are destroyed before they render. |
| SP3 | The header drops Co-Pilot / Sign out in the chart (not asked for) | **Kept.** The chart's patient menu has the module tabs, and Sign out inside the chart would lead to a standalone sign-in. Tested in `ehr-launch.test.tsx`. |
| SP4 | The guard's ACL calls ran on every load, even with the setting on legacy | **Fixed.** The setting is read first, so nothing new runs on legacy. |
| SP5 | Recent patients and "back to dashboard" are not tested | **Recorded.** Same page and path: `$requestedPid` falls back to the session pid. |

After the fixes:
- `in-chart.spec.ts` + `known-limits.spec.ts`: 10 of 10.
- Legacy security: 15 of 15.
- Parity (pids 1, 3, 5): 3 of 3.
- Standalone e2e: 4 of 4.
- PHPStan and PHPCS clean for the changed files.
