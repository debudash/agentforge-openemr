# templates/patient/card/amendments.html.twig

**Role:** the Amendments card body.
**Size:** 11 lines. **Reached from:** demographics.php L1473.

## Purpose and behaviour

One link per amendment (date and description) to its edit page.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Values escaped; `btnClass` printed raw.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-AM-01 | Low | L6 + demographics.php L1464 | **`btnClass` is always empty**: the page passes `btnCLass` (capital L). |

## What the port keeps

Outside the brief.
