# interface/patient_file/summary/track_anything_fragment.php

**Role:** body of the Tracks card. **Size:** 58 lines.
**Reached from:** `placeHtml("track_anything_fragment.php", …)` (demographics.php L628), unconditionally.

## Purpose and lifecycle

Checks CSRF, then lists each "track anything" form the patient has, with its newest result
timestamp (L16-39). Each entry links to the track's history page.

## Controls

**CSRF:** checked. **Authorization:** none, on the page or here. **Escaping:** `text()`, `attr_url()`.

## Database touches

Reads `forms`, `form_track_anything_results`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TAF-01 | Medium | L4-23 | **No authorization anywhere** for this card. |
| TAF-02 | Low | L16-22 | **`GROUP BY form_name` with a non-aggregated `form_id`**: the link target is whichever row the database picks, and the query fails under `ONLY_FULL_GROUP_BY`. |
| TAF-03 | Low | L12, L38 | **Duplicate id `labdata`** (the labs fragment's) and a doubled `</li>`. |

## What the port keeps

Outside the brief.
