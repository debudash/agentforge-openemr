# Changes made to the local dev stack in Phase 4

Local `docker/development-easy` stack only. Nothing here was done on Railway. Commands run from
the repository root in Git Bash unless noted.

```bash
SQL='docker compose -f docker/development-easy/docker-compose.yml exec -T mysql mariadb -uopenemr -popenemr openemr -e'
```

## OAuth clients

| Client | State | Remove |
|---|---|---|
| `pB6GFK_o8Ium1cjJISg1e1FBpSh1oD3XELVtco7fi64` "Patient Dashboard (local)", public, redirect `https://localhost:9300/public/dashboard/`, `patient/*.rs` scopes | In use: `dashboard/.env.local` (gitignored) holds its id | `$SQL "DELETE FROM api_token WHERE client_id='pB6GFK_o8Ium1cjJISg1e1FBpSh1oD3XELVtco7fi64'; DELETE FROM oauth_clients WHERE client_id='pB6GFK_o8Ium1cjJISg1e1FBpSh1oD3XELVtco7fi64'"` |
| `BC1OPvb0PJttDjSCR5GeirM0D0oD8a8P989Pm0N8ZJU` (4.0 spike, `http://localhost:5173/`) | Deleted, with its tokens | — |
| `e7u5E0tyH2LfXyGzCyK_9d7-Ie22cuYpOfe1QU54JCM` (first `public/dashboard/` client, no Organization scope) | Deleted, with its tokens | — |
| `Wy2CaW1mCQVKdNwIg9jy2jn_F1z8GUZMLEWagB6jdys` (4.0 same-origin spike) | Deleted, with its tokens | — |

Every harness and e2e run signs doctor1 in through this client, so `api_token` and
`oauth_trusted_user` gain rows per run. They expire on their own; the delete above removes them
(add `DELETE FROM oauth_trusted_user WHERE client_id=…` for the second table).

## Users and ACL groups (ADR 0005)

Created by `dashboard/e2e/setup/restricted-users.php create`; passwords are in the gitignored
`dashboard/e2e/.auth/restricted-users.json`.

| User | ACL group | Permissions |
|---|---|---|
| `dash-demoview` | Dashboard Demographics View | `patients/demo` view |
| `dash-nodemo` | Dashboard No Demographics | `patients/appt` view |

Each also has a `groups` row ("Default"), which login requires.

Remove (users, `users_secure`, `groups` rows, gacl AROs and both ACL groups):

```bash
docker compose -f docker/development-easy/docker-compose.yml exec -T openemr su -s /bin/sh apache -c \
  "php /var/www/localhost/htdocs/openemr/dashboard/e2e/setup/restricted-users.php remove"
rm dashboard/e2e/.auth/restricted-users.json
```

## Data

| What | Why | Remove |
|---|---|---|
| Care team "Primary care team" for pid 1 (doctor1 active, doctor2 inactive) and "Pediatrics" for pid 3 (doctor2), saved through the legacy Care Team form by `dashboard/e2e/setup/seed-care-team.mjs` | No patient had a care team; the Care Team card and the parity harness need one, and API-08 needs an inactive member | `$SQL "DELETE m FROM care_team_member m JOIN care_teams t ON t.id=m.care_team_id WHERE t.pid IN (1,3); DELETE FROM care_teams WHERE pid IN (1,3)"` |
| `recent_patients` rows for doctor1 and the test users | Written by the legacy page on every `set_pid` | Harmless; `$SQL "DELETE FROM recent_patients WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'dash-%')"` |
| Audit `log` rows `copilot-link-*` | Written by the ADR 0006 refusal path during its tests | Audit data; leave |

The legacy reproduction tests restore what they change: pid 44's squad, pid 1's team name, pid 3's
care team member notes, and every preference row marked `dashboard-e2e`.

## Files served by OpenEMR

`public/dashboard/` holds the built app (gitignored). Remove with `rm -rf public/dashboard`.
