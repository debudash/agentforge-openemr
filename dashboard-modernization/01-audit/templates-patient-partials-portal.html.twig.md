# templates/patient/partials/portal.html.twig

**Role:** the Patient Portal / API Access card body.
**Size:** 89 lines. **Reached from:** PortalCard via the secondary section.

## Purpose and behaviour

Alerts when the portal is disabled, misconfigured or not allowed for this patient, when email is
missing or enforced, and when API access is prevented; an "Assign documents" button; and a
Create/Reset credentials link when the portal is usable **or** API access is allowed (L63-75).

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Values escaped.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-PO-01 | Low | L11-15 | **Imports the injection macro, assigns its output to `prepend`/`append`, and never prints them.** |
| TPL-PO-02 | Low | L63-75 | **`… or isApiAllowed == true` binds loosely**: the credentials link shows whenever API access is allowed, even if the portal is off. May be intended; the precedence makes it unclear. |

## What the port keeps

Outside the brief.
