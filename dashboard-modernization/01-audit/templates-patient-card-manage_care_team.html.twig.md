# templates/patient/card/manage_care_team.html.twig

**Role:** the Care Team card body: read view and inline edit form in one.
**Size:** 227 lines. **Reached from:** CareTeamViewCard.

## Purpose and behaviour

Inside the card body it opens a second `<html><head>` (L3-4), calls `setupHeader()` to load the
datetime picker (L6), and defines a script that builds the members table **in the browser**: for
each member in `existing_care_team` it creates a `<tr>` with `innerHTML` from a template literal
(L44-78) containing the member name, role, facility, since date, status and **note**, then selects
the right option in each dropdown and copies the option text into the view spans (L87-101). Edit
mode toggles `.editShow`/`.viewOnly`. The form posts to the dashboard itself (L168) with the CSRF
token; `save_care_team=true` triggers the save in the card's constructor.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Server values reach the script via `js_escape` (safe as JS strings), **but are then inserted
into `innerHTML` and into `value="…"` attributes without HTML escaping.**

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-CT-01 | High | L52, L72-73 | **Stored XSS through the care-team note.** `${member.note}` is written into `innerHTML` (L72) and into an attribute value (L73) unescaped. A note such as `<img src=x onerror=…>` runs for every user who opens the patient's dashboard. The member name at L52 is later overwritten with `textContent` (L98); the note is not. Combined with CTC-01 (no permission needed to save), any user who can view a dashboard can plant it. Verified by code reading; not reproduced live. |
| TPL-CT-02 | Medium | L3-7, L164, L226 | **Nested `<html><head>` and a second `setupHeader()` mid-body**, reloading scripts into a page that already has them. |
| TPL-CT-03 | Low | L200 | **`.editOnly` class** used nowhere else. |

## What the port keeps

**Required by the brief (Care Team).** Read-only: members with type, role, facility, since, status, note; team name and status badge. Rendered as text nodes, never `innerHTML`.
