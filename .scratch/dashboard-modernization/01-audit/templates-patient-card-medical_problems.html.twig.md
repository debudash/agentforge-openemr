# templates/patient/card/medical_problems.html.twig

**Role:** the Medical Problems card body, also reused by stats.php for other issue types and Old Medication.
**Size:** 24 lines. **Reached from:** demographics.php L1158; stats.php L223, L332.

## Purpose and behaviour

Lists `title` for each active problem. Empty state: "None" (`None{{Issues}}`) when touched, else
"Nothing Recorded".

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Titles are `|text`-escaped.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-MP-01 | Low | L17-21 | **Only the title is shown**: no onset date, no code, no status. Parity is title-only. |

## What the port keeps

**Required by the brief (Problem List).** Parity: active problems, title only, same two empty states.
