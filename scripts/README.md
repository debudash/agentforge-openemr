# Scripts

Setup helpers for the demo environments. Everything here writes through OpenEMR's
own forms and APIs — never raw SQL — so validation, UUID assignment, events and
audit logging all run (see [AUDIT.md](../AUDIT.md) C1b).

They run from the `usecases` virtual environment, which already has `requests`:

```powershell
cd usecases
.venv\Scripts\python ..\scripts\<script>.py ...
```

## Provider accounts and panel assignment

Creates `doctor1` (Dana Reyes) and `doctor2` (Samir Okafor) as full providers —
`active`, `authorized` (provider), calendar access, Physicians ACL group, default
facility — then splits the patient panel evenly between them.

### 1. Create the accounts

```powershell
# local
.venv\Scripts\python ..\scripts\create_doctors.py https://localhost:9300 pass "<doctor password>"

# railway
.venv\Scripts\python ..\scripts\create_doctors.py https://<app>.up.railway.app "<admin password>" "<doctor password>"
```

The password must satisfy the live policy: at least 9 characters (`gbl_minimum_password_length`)
and strong (`secure_password=1`) — a number, a lowercase letter, an uppercase letter
and a special character.

### 2. Grant the ACL group if the POST returned 500

`AclExtended::setUserAro()` needs an **array of group titles** (`["Physicians"]`),
not the gacl value (`doc`). When it receives a string it throws, so the request
500s *after* the user row is inserted: the account exists but has no permissions.
`create_doctors.py` posts `access_group[]` correctly; use `fix_acl.php` to repair
accounts created before that fix, or to change a group later.

```powershell
# local — must run as the web user; the image's RootCliGuard rejects root
copy scripts\fix_acl.php tmp\fix_acl.php
docker compose exec -T openemr su -s /bin/sh apache -c "php /var/www/localhost/htdocs/openemr/tmp/fix_acl.php"

# railway — no bind mount, so send the file over ssh
$php = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Content scripts\fix_acl.php -Raw)))
railway ssh --service openemr sh -c "echo $php | base64 -d > /tmp/fix_acl.php && php /tmp/fix_acl.php && rm -f /tmp/fix_acl.php"
```

Verify: `SELECT a.value, g.name FROM gacl_aro a JOIN gacl_groups_aro_map m ON m.aro_id=a.id JOIN gacl_aro_groups g ON g.id=m.group_id WHERE a.value LIKE 'doctor%';`

### 3. Assign the panel

```powershell
# local
$env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"
.venv\Scripts\python ..\scripts\assign_patients.py

# railway
$env:OPENEMR_BASE_URL="https://<app>.up.railway.app"; $env:OE_PASS="<admin password>"
$env:OE_DB_VIA="railway"; $env:OE_DB_PASS="<openemr db password>"
.venv\Scripts\python ..\scripts\assign_patients.py
```

Patients are split by `pid`: the first half to `doctor1`, the rest to `doctor2`.
The script registers a temporary OAuth client, enables it, does the updates via
`PUT /api/patient/:puuid`, deletes the client, then prints the resulting counts.

Re-running is safe: it overwrites `providerID` with the same split.

## CopilotAgent menu tab

`interface/modules/custom_modules/oe-module-copilot-agent` adds a top-level
**CopilotAgent** tab via the `MenuEvent::MENU_UPDATE` hook, rather than editing
`interface/main/tabs/menu/menus/standard.json` (tracked upstream, so edits there
conflict on every merge from OpenEMR master).

### Registering it

OpenEMR only loads a custom module's bootstrap when its `modules` row has
`mod_active = 1`, and Manage Modules is a UI-only flow. This writes the same rows
the Installer would:

```powershell
cd usecases
.venv\Scripts\python ..\scripts\register_module.py                        # local
$env:OE_DB_VIA="railway"; $env:OE_DB_PASS="<db pw>"
.venv\Scripts\python ..\scripts\register_module.py                        # railway
```

Re-run it after a fresh install, a database rebuild or a snapshot restore. It is
idempotent: an existing row is re-enabled rather than duplicated.

### Writing module code that runs on both images

The local stack runs `openemr/openemr:flex` (master) and Railway runs
`openemr/openemr:latest` (stable). Several `OEGlobalsBag` methods exist **only on
master**, and a fatal inside a module bootstrap takes down *every* page, because
bootstraps are included by `globals.php`:

| Master-only call | Use instead |
|---|---|
| `OEGlobalsBag::getProjectDir()` | `dirname(__DIR__, 4)` |
| `OEGlobalsBag::getKernel()` | `$GLOBALS['kernel']`, with `method_exists()` first |
| `OEGlobalsBag::getWebRoot()` | nothing — menu URLs are site-root relative |
| `SessionWrapperFactory::getActiveSession()` | `UserService::getCurrentlyLoggedInUser()` |

Wrap the whole bootstrap in `try/catch (\Throwable)` and `error_log()` the
failure, so a broken tab degrades to a missing tab instead of an unusable site.

### Keeping it alive on Railway

The Railway service runs the stock image with no bind mount, so module files
copied into the container are lost on redeploy — and OpenEMR then force-disables
the module after three failed bootstrap reads. The module therefore lives on the
persistent volume and is symlinked into place:

```
sites/default/copilot-module                                   <- real files (on the volume)
interface/modules/custom_modules/oe-module-copilot-agent       -> symlink
```

To restore it after a redeploy, recreate the symlink and re-run
`register_module.py`:

```powershell
railway ssh --service openemr sh -c "ln -sfn /var/www/localhost/htdocs/openemr/sites/default/copilot-module /var/www/localhost/htdocs/openemr/interface/modules/custom_modules/oe-module-copilot-agent"
```

## Today's rounding list (co-pilot)

The co-pilot lists *today's appointments booked for the signed-in provider, restricted to
that provider's assigned patients*. Synthea data has no calendar events, so book them:

```powershell
cd usecases
$env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"
.venv\Scripts\python ..\scripts\seed_appointments.py                 # 12 per doctor, today, 08:00 onwards
.venv\Scripts\python ..\scripts\seed_appointments.py --days 5        # today and the next four days
.venv\Scripts\python ..\scripts\seed_appointments.py --per-doctor 6 --date 2026-09-20
```

Writes go through `POST /api/patient/:pid/appointment`. Re-running a date first removes that
day's `Rounding (co-pilot demo)` bookings, so it never duplicates and the list can be moved
day to day. One OAuth client covers the whole run, however many days it books. The script
exits non-zero if any date ends up short, so a scheduler can detect a partial run.

Dates default to the **server's** date, which is UTC in the containers and can already be
tomorrow late in your evening. That default is the correct one, because it is the date the
co-pilot itself reads.

For the Railway deployment add `OE_DB_VIA=railway` and `OE_DB_PASS`. On Railway this runs
nightly on its own; see "Nightly rounding-list seeding" in
[deploy/railway/README.md](../deploy/railway/README.md).

### Shared access module

`oe_api.py` holds the configuration, `db_query` and the temporary-OAuth-client helper that
the scripts, the test suite and the Railway cron container all use, so there is one code
path rather than three. `usecases/conftest.py` re-exports its names, so
`from conftest import db_query` keeps working everywhere it was already used.

`db_query` reaches MariaDB three ways, chosen by `OE_DB_VIA`:

| mode | how | used by |
|---|---|---|
| `docker` (default) | `docker compose exec` | the local stack |
| `railway` | `railway ssh` into the openemr service | a laptop with the Railway CLI |
| `mysql` | a direct connection (PyMySQL) | the Railway cron container |

Only `mysql` mode needs PyMySQL, and it is imported lazily, so the other two run without it.

## Changing a user's password

`set_user_password.py` posts the user-administration *update* form with the admin's
re-authentication, so the password policy and audit logging apply. Passwords come from
environment variables, never argv:

```powershell
cd usecases
$env:OE_PASS="<admin pw>"; $env:OE_DOCTOR_PASS="<new pw>"
.venv\Scripts\python ..\scripts\set_user_password.py https://localhost:9300 doctor1 OE_PASS OE_DOCTOR_PASS
```

**Gotcha found the hard way:** the update handler replaces ACL group membership with the
`access_group[]` values in the POST. Omit them and the user is removed from every group, and
OpenEMR then refuses the login with "user not in any phpGACL groups". The script re-sends
the current groups and prints them afterwards; `fix_acl.php` repairs an account that lost them.

## Why this matters

`USERS.md` scopes the agent to one clinician's patients, and `AUDIT.md` S3 notes
that user-level OAuth scopes reach every patient with no care-team restriction.
An assigned provider per patient is what makes provider-scoped access testable.
