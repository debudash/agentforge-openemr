# src/Patient/Cards/PortalCard.php

**Role:** the "Patient Portal / API Access" card in the secondary section.
**Size:** 115 lines. **Reached from:** `new PortalCard($GLOBALS)` at demographics.php L1590 when the portal or any API is enabled.

## Purpose and lifecycle

The constructor builds its options immediately (L41-70): it queries the DEM layout's group 4 title,
and calls five functions that exist only because demographics.php declared them
(`isPortalEnabled`, `isPortalSiteAddressValid`, `isPortalAllowed`, `isApiAllowed`,
`areCredentialsCreated`, `isContactEmail`, `isEnforceSigninEmailPortal`), using `global $pid`
(L43). It dispatches its render event, then registers a listener on `SectionEvent` (L75-78) that
adds a copy of itself to **any** section dispatched later (L79-85). The page dispatches the
secondary section right after (L1595), so that is where it appears.

## Controls

ACL `patients/demo` (L50). The template offers a Create/Reset credentials link for the portal.

## Database touches

Reads `layout_group_properties`, `patient_data` (three times via the page functions),
`patient_access_onsite`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| PTC-01 | Medium | L43-67 | **Depends on functions declared in the entry page and on `global $pid`**; the class cannot be used anywhere else. |
| PTC-02 | Low | L75-85 | **Listens to every SectionEvent** and adds itself unconditionally (`if ($e->getSection())` is always true for a named section). |
| PTC-03 | Low | demographics.php L1590 | **Constructed with `$GLOBALS`**, which the constructor ignores. |
| PTC-04 | Low | L48 | **Null row not handled** when the layout has no group 4. |

## What the port keeps

Outside the brief.
