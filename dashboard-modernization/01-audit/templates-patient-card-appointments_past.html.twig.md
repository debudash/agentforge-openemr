# templates/patient/card/appointments_past.html.twig

**Role:** an old past-appointments card body.
**Size:** 12 lines. **Reached from:** **nowhere** — no PHP renders it.

## Purpose and behaviour

Dead. Lines 9-10 are PHP source (`echo text(...)`) pasted into the Twig file as literal text; the variables it reads (`appt`, `a.dayname`, `a.category`, `a.petitle`) are not what the page produces.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-APP-01 | Low | whole file | **Dead, broken template** containing PHP source as text. |

## What the port keeps

Nothing.
