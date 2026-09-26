# src/Patient/Cards/DemographicsViewCard.php

**Role:** the Demographics card in the primary section.
**Size:** 79 lines. **Reached from:** `addCard(new DemographicsViewCard($result, $result2, …))` at demographics.php L1340.

## Purpose and lifecycle

It carries the full `patient_data` row and the employer row, and on render dispatches its
`RenderEvent` and returns template variables for `tab_base.html.twig`: tab id `DEM`, title, edit
link `demographics_full.php`, and the data rows. The template calls `display_layout_tabs()` and
`display_layout_tabs_data()` from `options.inc.php`, which render the DEM layout (the
administrator-configurable Layout Based Form of demographic fields) group by group.

## Controls

ACL `patients/demo` (L19), checked by the page (L1357-1360). Edit is shown with write access
(L42). Escaping happens inside `display_layout_tabs*()`.

## Database touches

None directly; the layout functions read `layout_options` and list tables.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| DVC-01 | Low | L42 | **`ACLMain` vs `AclMain`** (class names are case-insensitive in PHP, so it works). |
| DVC-02 | Low | L18-29, L39-58 | **Options are set twice** (constructor and render) with the same values. |

## What the port keeps

The header fields come from this data (name, DOB, sex, pubpid). The full demographics layout is
admin-configurable per site and is outside the brief.
