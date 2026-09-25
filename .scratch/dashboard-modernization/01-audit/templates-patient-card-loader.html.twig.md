# templates/patient/card/loader.html.twig

**Role:** placeholder card body (spinner) for cards filled by AJAX fragments.
**Size:** 9 lines. **Reached from:** demographics.php for Messages, Patient Reminders, Disclosures, Labs, Vitals, LBF forms, Clinical Reminders, Tracks.

## Purpose and behaviour

Extends `card_base` and renders a "Loading..." spinner; the page later replaces the body with the fragment's HTML via `innerHTML`.

## Controls

None needed; static text is `xlt`-escaped.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-LD-01 | Low | L4-8 | **The spinner stays forever if the fragment request fails silently**, and error pages replace it verbatim (see DEM-11). There is no error state. |

## What the port keeps

Loading and error states per card; the port renders a skeleton while its query is pending and an explicit error state when it fails.
