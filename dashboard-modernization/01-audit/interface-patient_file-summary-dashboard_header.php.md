# interface/patient_file/summary/dashboard_header.php

**Role:** renders the page heading at the top of the dashboard, and of other patient pages that include it.
**Size:** 36 lines. **Reached from:** `require_once` at demographics.php L1076, only when `$thisauth`.

## Purpose and lifecycle

It builds a new Twig container, reads the session and renders `patient/dashboard_header.html.twig`
with three variables: `pageHeading` (the HTML from `OemrUI::pageHeading()`, which dispatches
`PageHeadingRenderEvent` so modules can add menu items and buttons), `pid`, and a CSRF token. It
relies on the including page to have defined `$oemr_ui` and `$pid` in its scope (L27-31) and falls
back to the session pid.

## Controls

None of its own; it trusts the caller's authorization. `pid` and `csrf` are passed to a template
that does not use them.

## Database touches

None directly. The heading event's listeners may query.

## Globals and session

Reads `$oemr_ui` and `$pid` from the including scope, and the session.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| HDR-01 | Low | L23-24 | **A second Twig container per request.** The dashboard already built one (demographics.php L81); this builds another with default settings. |
| HDR-02 | Low | L30-34 | **Unused variables.** `pid` and `csrf` are passed to the template and ignored. |

## What the port keeps

Nothing structural. The heading is page chrome ("Medical Record Dashboard" plus module buttons);
the patient's identity lives in the tabs shell's identity bar.
