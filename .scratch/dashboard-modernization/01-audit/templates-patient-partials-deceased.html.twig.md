# templates/patient/partials/deceased.html.twig

**Role:** the red "Deceased - date (n days ago)" banner.
**Size:** 17 lines. **Reached from:** demographics.php L1334 when `is_patient_deceased()`.

## Purpose and behaviour

Prints `deceasedDays` (built by `deceasedDays()` in demographics.php L282-305: "Today", "n days
ago", "~n months ago", "More than n years ago").

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. `|text`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-DC-01 | Low | L1-3 | **Header comment says "Patient Portal card"** (copied). |

## What the port keeps

**Deceased status belongs in the port's header** (the brief's "active status" is where it is surfaced). Keep the relative-age wording.
