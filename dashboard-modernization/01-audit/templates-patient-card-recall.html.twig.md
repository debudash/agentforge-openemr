# templates/patient/card/recall.html.twig

**Role:** the Recall card body.
**Size:** 18 lines. **Reached from:** demographics.php L1913.

## Purpose and behaviour

Lists recall reasons and dates; each row, and the "No Recalls" row, links to the recall board's
add screen.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Values escaped.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-RC-01 | Low | L8, L14 | **Links open "add recall" without the patient or recall id**, so the clinician starts from an empty form. |

## What the port keeps

Outside the brief.
