# interface/main/tabs/js/frame_proxies.js

**Role:** the bridge legacy pages use to talk to the tabs shell (`left_nav.*`, `RTop`). **Size:** 146 lines.
**Reached from:** every legacy page that calls `parent.left_nav.*`; the dashboard calls `setPatient`, `setPatientEncounter`, `syncRadios`, `setEncounter`, `loadFrame`.

## Purpose and lifecycle

`left_nav.setPatient()` (L27-54): if the same pid is already active, it updates the name, pubpid and
DOB string; otherwise it creates a new patient view model, clears any therapy group, sets the window
title to include the patient name (if `WindowTitleAddPatient`), reloads the encounters tab and
switches the attendant template to the patient bar. `setPatientEncounter()` (L82-91) replaces the
encounter list. `setEncounter()` (L93-96) selects one. `loadFrame()` (L98-107) opens a URL in a named
tab.

## Controls

None. It trusts the calling page for the patient's identity and for the encounter list — which is
why DEM-01 matters: the dashboard pushes identity before it has checked authorization.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| FPX-01 | Low | L27-54 | **Identity is pushed by whichever page calls it**, with no check that the pid matches the session. A page can show one patient in the bar and another in the body. |
| FPX-02 | Low | L43 | **Patient name in the window title** (when enabled) is visible in the OS task switcher and screen shares. |

## What the port keeps

Nothing. The new dashboard owns its own header; if embedded in the shell later, it would call
`setPatient` the same way.
