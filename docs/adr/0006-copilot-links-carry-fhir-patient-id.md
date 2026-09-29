# 0006. Co-Pilot and Demo Data are linked from the new dashboard by FHIR patient id

Status: accepted (2026-09-25). Supersedes: none.

## Context

The Co-Pilot and Demo Data tabs are added to the legacy chart's patient navbar by our module
(`oe-module-copilot-agent`, `Bootstrap::addPatientTab`). Both pages read the patient from the PHP
session (`ActivePatient`) and never from the URL. The new dashboard has no navbar and no PHP
session; its patient comes from the SMART launch as a FHIR id. A plain link would open the module
page for whichever patient the session holds, which can differ from the one on screen.

## Decision

The new dashboard's header links to both pages with `?patient=<FHIR uuid>`. The module page
resolves the uuid and refuses unless it matches the session patient. The refusal names the
mismatch and offers to open the chart for the dashboard's patient. With no parameter the page
behaves as today. Demo Data is linked only when `demoTools` is on. Details: spec §12.1.

## Consequences

- A wrong-patient view is refused, not shown.
- This changes our module, not OpenEMR core. The defense states that the brief's "no backend
  changes" is read as OpenEMR's backend.
- The SMART login does not create an OpenEMR session, so without one the link lands on
  OpenEMR's login page.
- The refusal path needs tests for matching, mismatched and unknown ids, no session, and no
  parameter. Whether the pages render outside the tabs shell is checked in the Phase 4.0 spike.
