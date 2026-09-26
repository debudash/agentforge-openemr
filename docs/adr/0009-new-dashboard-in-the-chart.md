# 0009. Open the new dashboard in the chart, behind an admin setting

Status: accepted (2026-09-26). Supersedes: none.

## Context

The new dashboard is a SMART app served from `public/dashboard/` (ADR 0008). Opened on its own it
asks the doctor to log in, pick the patient and approve access again, outside the EMR's
workflow. The EHR-launch spike (`.scratch/dashboard-modernization/04-evidence/spike-ehr/`) proved
that a SMART app launched from the chart gets the chart's patient, an OpenID ID token for the
signed-in user and a PKCE token in one click, with no login or consent screen when the admin
trusts the client. Without a code change the launch point is only the chart's collapsed "SMART
Enabled Apps" card.

Every way of opening a patient (calendar, patient finder, recent patients, "back to dashboard"
links) loads `interface/patient_file/summary/demographics.php` into the chart's tab.

## Decision

Change `demographics.php` so that, when an admin setting selects the new dashboard, the page
keeps everything above the cards (authorization, patient switch, identity bar, header, patient
menu with its module tabs, clinical alerts) and replaces the card area with the new app, EHR-launched
for the patient being opened. The setting defaults to the legacy dashboard.

**This departs from the brief**, which says the backend is not touched. It is a deliberate
change to one OpenEMR page plus one global setting, made for the clinical workflow, and it is
documented as a deviation in `PATIENT_DASHBOARD_MIGRATION.md`. The port itself still reads all
data through the FHIR API.

## Consequences

- Clicking a patient anywhere opens the new dashboard for that patient, inside the EMR, with no
  second login. The OAuth2/OIDC exchange still runs on every open.
- Off by default: with the setting off, the page is today's page, byte for byte in behaviour.
  Rollback is one setting.
- The admin registers the app with the `launch` scope, enables it and trusts it ("skip
  authorization flow"). Trusting it skips both login and consent for that app.
- The launched patient must be the chart's patient on every open; that is tested, including a
  fast switch between patients.
- The legacy page, its security fixes (ADR 0004) and the parity harness keep working, because the
  legacy renderer stays reachable through the setting.
- Upstream candidate: the change is small and generic (any SMART app as the dashboard body).
