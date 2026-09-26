# templates/patient/dashboard_header.html.twig

**Role:** prints the page heading HTML.
**Size:** 1 line. **Reached from:** dashboard_header.php.

## Purpose and behaviour

`{{ pageHeading }}` — raw HTML from `OemrUI::pageHeading()`. This works only because autoescaping
is off; with it on, the heading would print as escaped text.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it.

## Findings

No findings.

## What the port keeps

Nothing.
