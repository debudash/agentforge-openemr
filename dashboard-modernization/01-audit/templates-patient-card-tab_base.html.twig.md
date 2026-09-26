# templates/patient/card/tab_base.html.twig

**Role:** card body that renders a Layout Based Form's tabs (used for Demographics).
**Size:** 10 lines. **Reached from:** DemographicsViewCard.

## Purpose and behaviour

`tabRow(tabID, result, result2)` prints the tab headers and `tabData(...)` the fields, both via
`display_layout_tabs*()` in options.inc.php captured by output buffering.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Escaping happens inside the layout functions.

## Findings

No findings.

## What the port keeps

Outside the brief (site-configurable demographics layout).
