# interface/patient_file/summary/disc_fragment.php

**Role:** body of the Disclosures card. **Size:** 114 lines.
**Reached from:** `placeHtml("disc_fragment.php", "disclosures_ps_expand")` (demographics.php L626), unconditionally; the target div exists only when the user has `patients/disclosure`.

## Purpose and lifecycle

Checks CSRF (L10), loads the three newest disclosure events for the session patient from
`extended_log`, keeping only events whose type is an active `disclosure_type` (L17-30), and prints
type, provider and a date/recipient/description summary. When there are none it offers a link to
record one if the user has write or add-only rights.

## Controls

- **CSRF:** checked.
- **Authorization:** **none** on read. The page shows the card only with `patients/disclosure`
  (demographics.php L1424), but this script returns the data to any authenticated user who posts a
  valid token. No squad check.
- **Escaping:** `text()` throughout.

## Database touches

Reads `extended_log`, `users`, `list_options`. No writes.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| DSF-01 | High | L4-46 | **No authorization on the endpoint** (the fragment pattern FRG in the catalog). |
| DSF-02 | Low | L52-57 | **`$event[1]` is undefined** when an event name has no hyphen. |
| DSF-03 | Low | L32, L67 | **Container id is `pnotes`**, the notes card's name; missing space in `valign='top'class`. |
| DSF-04 | Low | L42 | **Count hard-coded to 3.** |

## What the port keeps

Outside the brief's required set.
