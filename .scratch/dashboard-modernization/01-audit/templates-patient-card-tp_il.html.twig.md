# templates/patient/card/tp_il.html.twig

**Role:** card body for the Treatment Protocols / Injury Log spreadsheet forms.
**Size:** 15 lines. **Reached from:** stats.php L251.

## Purpose and behaviour

One link per form row. Receives a single associative array from stats.php (STA-05), so the loop
iterates its keys, not rows.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-TP-01 | Low | L6 | **Iterates a flat array as if it were rows** (consequence of STA-05). |

## What the port keeps

Outside the brief.
