# src/Patient/Cards/CareTeamViewCard.php

**Role:** the Care Team card: its view data, its edit form's option lists, and the handler that saves the form.
**Size:** 389 lines. **Reached from:** `new CareTeamViewCard($pid, …)` at demographics.php L1253, on every dashboard render unless the card is hidden globally.

## Purpose

It shows the patient's care team (members who are users or related persons, each with role,
facility, "since" date, status and note) and a team status badge, and it provides everything the
inline edit form needs: option lists of all active users, facilities, roles and statuses, and the
patient's related persons. The template (`manage_care_team.html.twig`) builds the table in the
browser from this data.

## Lifecycle

1. **Constructor** (L25-31) sets options (ACL `patients/demo`, title, template), then calls
   `handleFormSubmission()`.
2. **`handleFormSubmission()`** (L97-117) runs on every construction. If the POST body has
   `save_care_team=true`, it checks the CSRF token, reads `team_id`, `team_name`, `team_status` and
   the `team[]` array, and calls `CareTeamService::saveCareTeam()`. The form posts to the dashboard
   itself (`action=""`), so saving is "load the dashboard with a POST body".
3. **`getTemplateVariables()`** (L87-96) runs when the page renders the card: dispatches the card's
   `RenderEvent`, asks whether an active team exists, then `getFormManagementData()`.
4. **`getFormManagementData()`** (L126-305) loads the team and its members; calls
   `ContactService::getOrCreateForEntity('patient_data', $pid)` (L154), which **creates a contact
   row** for the patient if none exists; loads related persons; queries **all active users** and all
   service/billing facilities; loads role and status lists; and builds `<option>` HTML strings in PHP
   for each list.

## Controls

- **Authorization:** the card declares ACL `patients/demo`. The page checks it at L1271, **after**
  the constructor has already run the save handler. The save itself checks **no** permission:
  `$authCheck` (write) at L64 only decides whether the Edit button is shown.
- **CSRF:** checked on save (L103).
- **Escaping:** option strings are built with `attr()`/`text()` (L215-284). The member rows are
  built in the browser with `innerHTML` from JSON (template L45-78); the note is never escaped there
  (TPL finding in manage_care_team).

## Database touches

Reads the care team tables through `CareTeamService`, `contact`/`contact_relation` through
`ContactService`/`ContactRelationService`, `users` + `list_options` (L163-167), `facility`
(L179-185), `list_options` (roles, statuses). Writes the care team (save path) and a `contact` row
(render path, L154).

## Globals and session

POST body via `HttpRestRequest::createFromGlobals()` (L99); session for the CSRF token.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| CTC-01 | Critical | L25-31, L97-117 | **Saving a care team needs no permission.** Any user who can open a patient's dashboard (and so holds a CSRF token) can replace that patient's care team by posting `save_care_team=true`. The write happens in the constructor, before the page's own card ACL check (demographics.php L1271), and there is no write-ACL check in the handler. Verified by code reading; not reproduced live. |
| CTC-02 | Medium | L152-154 | **Viewing the dashboard writes to the database.** `getOrCreateForEntity()` inserts a `contact` row for the patient the first time the card renders. |
| CTC-03 | Medium | L163-194 | **Every render loads every active user and facility** to build option lists that are only needed if someone clicks Edit. |
| CTC-04 | Low | L57-60 | **`getViewArgs()` returns the template path**; the name and the docblock (`@return array`) are both wrong. |
| CTC-05 | Low | L138-147 | **Member fields the template reads are not provided** (`role_display`, `facility_display`, `status_display`, `user_display`); the template patches the text in afterwards from the select boxes. |

## What the port keeps

The **Care Team card** is required by the brief. The rows to show: member name, member type
(provider or related person), role, facility, since date, status, note; the team name and status
badge; active and inactive members distinguished. FHIR `CareTeam?patient=` supplies
`participant[].member`, `role`, `period`, `status`, `name`. Editing is out of scope for the port.
