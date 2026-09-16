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

## Why this matters

`USERS.md` scopes the agent to one clinician's patients, and `AUDIT.md` S3 notes
that user-level OAuth scopes reach every patient with no care-team restriction.
An assigned provider per patient is what makes provider-scoped access testable.
