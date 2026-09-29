# src/Menu/PatientMenuRole.php

**Role:** builds the horizontal patient menu under the page heading.
**Size:** 288 lines. **Reached from:** `(new PatientMenuRole($twig))->displayHorizNavBarMenu()` at demographics.php L1081-1082.

## Purpose and lifecycle

`getMenu()` (L34-66) reads the user's patient menu role, loads either a standard JSON menu from
`interface/main/tabs/menu/menus/patient_menus/` or a custom one from the site's documents
directory, makes URLs absolute, lets the `Modules` entry pull in module hooks attached to
`demographics` (L117-159), dispatches `PatientMenuEvent::MENU_UPDATE`, applies ACL restrictions
(inherited `menuApplyRestrictions`), and dispatches `MENU_RESTRICT`. `displayHorizNavBarMenu()`
(L163-208) echoes a Bootstrap navbar.

## Controls

- **Authorization:** per-item ACL requirements applied by the parent `MenuRole`; module hooks checked
  with `zhAclCheck` (L134).
- **Path traversal:** the menu filename is rejected unless it is a bare basename (L39-42).
- **Escaping:** labels via `text()`, URLs and ids via `attr()`; **`on_click` is printed raw** (L187, L195).

## Database touches

Reads the current user, `modules_hooks_settings`, `modules_settings`, `modules`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| MNU-01 | Low | L187, L195 | **`onclick` from the menu JSON is printed unescaped.** Admin- or module-controlled, but still an injection point. |
| MNU-02 | Low | L41, L53 | **`die()` mid-render** on a bad filename or bad JSON, leaving half a page. |
| MNU-03 | Low | L19 | **Constructor takes no arguments**; the page passes `$twig`, which is ignored. |
| MNU-04 | Low | L134 | **Inverted-looking condition** `zhAclCheck(...) ? "" : "1"` that relies on string truthiness. |

## What the port keeps

The patient menu is navigation into legacy pages (Dashboard, History, Report, Documents,
Transactions, Issues, Ledger, External Data). The port links out to the same URLs; it does not
reimplement them.
