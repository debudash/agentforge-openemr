# Deploying OpenEMR to Railway

Public deployment of this fork, reachable over HTTPS at a `*.up.railway.app` address.

**Synthetic data only.** This deployment is on the public internet with the OAuth password grant enabled. Never load real patient data into it (see [AUDIT.md](../../AUDIT.md) §5).

**Cost:** the Hobby plan is $5/month including $5 of usage, then about $20/vCPU/month and $10/GB RAM/month, metered per minute, plus $0.15/GB/month for volumes. Two always-on services land around $15–25/month. Remove or scale the services to zero between demos and you pay for little more than the volumes.

---

## Current deployment (since 2026-09-25)

Railway runs **OpenEMR 8.2.0-dev built from this repository**, the same code the dev stack runs,
not the stock `openemr/openemr:latest` (8.0.0) it ran until then. The version skew between the
two broke the Week 2 deploy three times ([W2_ARCHITECTURE.md](../../W2_ARCHITECTURE.md), "one
codebase, two OpenEMRs"), so the platform was moved rather than guarded against forever.

| | |
|---|---|
| URL | `https://openemr-production-461d.up.railway.app` (unchanged) |
| Environment | `v82`, the project's only environment |
| Services | `openemr-v82`, `mysql-v82`, `copilot-agent-v82`, `copilot-seeder-v82` (cron 01:05 UTC) |
| Private hosts | `mysql-v82.railway.internal`, `copilot-agent-v82.railway.internal:8600` |
| OpenEMR image | `debulearn4ever/openemr-agent:8.2.0-dev-949e911`, pinned by digest (since 2026-09-26; adds the patient dashboard). Previous: `8.2.0-dev-9a73bae` |
| Data | 50 Synthea patients (25 per doctor), generated fresh; same `admin`/`doctor1`/`doctor2` passwords as before |

Service names carry `-v82` because Railway service names are unique per project, and the new
services were built beside the old ones before the switch.

### Building from this checkout

The co-pilot module is inside the OpenEMR image, so a module change ships as a new image:

1. `deploy/railway/build_openemr_image.sh` (Git Bash) exports a commit with `git archive`, builds
   upstream's `docker/release/Dockerfile` unchanged with `--build-context openemr-source=...`
   replacing its `git clone` of upstream master, checks the image holds that commit's OpenEMR and
   the module, and pushes to Docker Hub only after you type `DEPLOY`.
2. Run the image locally against a fresh MariaDB with the Railway variables and no bind mount, and
   go through the co-pilot as `doctor1` before Railway sees it.
3. `railway service source connect --image "<tag>@<digest>" --service openemr-v82`, then
   `.\deploy\railway\preflight_module.ps1`, which checks the live OpenEMR as the web server user
   and exits non-zero on any failure (63 checks).

The agent is unchanged: `.\deploy\railway\deploy_agent.ps1`.

### Patient dashboard

The new dashboard (`dashboard/`, ADR 0008) is built into the image's `public/dashboard/` by
`build_openemr_image.sh`, which also drops its source and write-ups from the web root. Its OAuth
client ID is compiled in, so the client comes first. One time per instance:

1. Register a public client (dynamic registration, `POST /oauth2/default/registration`) with
   `redirect_uris` and `initiate_login_uri` both `https://<host>/public/dashboard/`, and the scopes
   in `dashboard/src/auth/smart.ts` plus `launch`. Omit `token_endpoint_auth_method`.
2. Enable it and trust it (skips the second login and consent in the chart):
   `UPDATE oauth_clients SET is_enabled=1, skip_ehr_launch_authorization_flow=1 WHERE client_id='<id>'`.
   The global `oauth_ehr_launch_authorization_flow_skip` must be 1 (it is by default).
3. Build with the ID: `VITE_SMART_CLIENT_ID=<id> deploy/railway/build_openemr_image.sh`.
4. After the new image is live, turn the chart on (Admin > Globals > Appearance, or SQL):
   `patient_dashboard_renderer=smart_app` and `patient_dashboard_smart_client_id=<id>`. Rollback is
   `patient_dashboard_renderer=legacy`.

Production's client, registered 2026-09-26: `J1AhFXCvkrO3Fpd_ZqizB0L-GkNOaFePCL56jghk8Y4` (public,
so the ID is not a secret).

### Standing up a fresh instance: traps hit on 2026-09-24

- **An empty Railway volume at `sites/`** hides the image's `sites/default`. Set `SWARM_MODE=yes`
  for the **first boot only**: the image then copies `sites/` from `/swarm-pieces` into the empty
  volume before installing. Set it back to `no` afterwards.
- **Upstream's swarm takeover crash-loops.** If a leader file (`sites/docker-leader`) is left by a
  failed boot, the next container waits five minutes, takes over, then demotes itself in the same
  function and exits with `Critical failure! An OpenEMR worker is trying to run on a missing
  configuration.` -- forever. Recover with `rm sites/docker-leader` and `SWARM_MODE=no`.
- **Attach the volume and set the real `MYSQL_HOST` before the first deploy.** A service deploys
  the moment it is created; a first boot that fails is what leaves that leader file behind.
- **The first boot can race MariaDB's own first-time init** (`unable to connect to database as
  root`). Railway restarts on failure and the second attempt installs.
- **`sites/default` is read-only to apache** (mode 500) in this image. Create
  `sites/default/copilot-demo/generated` as root and `chown -R apache:apache` it, then write
  `sites/default/copilot-config.php` as in "Agent service" step 3.
- **Register the module** (`scripts/register_module.py`), create the doctors
  (`scripts/create_doctors.py`), import patients, assign the panel and seed appointments (below).
  Check the patient count after the import: one run of 50 produced 48.
- **`/meta/health/readyz` says `setup_required` on a working 8.2 install** (see the root
  CLAUDE.md) and still returns 200, so do not use it to judge an install.

### How the switch was made

The new services ran at their own address until they passed the preflight, the co-pilot as
`doctor1`, a live brief and follow-up, and the use-case suite. Then two domain renames, about
11 seconds apart:

```bash
railway domain update openemr-production-461d.up.railway.app --domain openemr-old-461d --service openemr --environment production
railway domain update openemr-v82-v82.up.railway.app --domain openemr-production-461d --service openemr-v82 --environment v82
```

A Railway-provided domain can be renamed, and the label it releases can be claimed straight away,
across environments. After the switch, `OPENEMR_SETTING_site_addr_oath` on `openemr-v82` and
`COPILOT_OPENEMR_URL` on `copilot-agent-v82` were set to the real URL. The old `production`
environment was deleted the same day, after its database and `sites/` were backed up off-site.

---

## How this differs from the local stack

| | Local (`docker/development-easy`) | Railway |
|---|---|---|
| Image | `openemr/openemr:flex` with this checkout bind-mounted | Built from this checkout (`build_openemr_image.sh`), digest-pinned; same OpenEMR version |
| TLS | Self-signed on port 9300 | Terminated at Railway's edge; container serves plain HTTP on port 80 |
| Certificates | Image generates them; `DOMAIN` triggers Let's Encrypt | **Never set `DOMAIN`** — certbot can't answer the ACME challenge behind Railway's proxy |
| Volumes | 13 volumes | **One per service** (a Railway limit): `sites/` and `/var/lib/mysql` |
| Service ordering | `depends_on: healthy` | Not supported, and not needed: the image's `wait_for_mysql()` retries |
| Extras | phpMyAdmin, CouchDB, Selenium, LDAP, Mailpit, Xdebug | None of them |
| Health check | Docker healthcheck, continuous | Railway healthcheck, **deploy time only** |

---

## Before you start

1. **A Railway account** at [railway.com](https://railway.com) (a GitHub login works), on the Hobby plan.
2. **The Railway CLI** (already installed in this workspace via `npm install -g @railway/cli`). Everything below can also be done in the dashboard.
3. **Four generated passwords.** In PowerShell:
   ```powershell
   1..3 | ForEach-Object { -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 28 | ForEach-Object {[char]$_}) }
   ```
   Keep them for `MYSQL_ROOT_PASS`, `MYSQL_PASS` and `OE_PASS`. Don't commit them; Railway stores them as service variables.

---

## Steps

> **Historical.** These are the steps for the original stock-image deployment, retired on
> 2026-09-25. To stand up an instance today, follow "Current deployment" above; the commands in
> the sections after "Custom modules" use today's service names.

### 1. Sign in and create the project

```powershell
railway login          # opens a browser; use `railway login --browserless` on a headless machine
railway init --name openemr-agent
```

### 2. Create the MariaDB service

We run the MariaDB image directly (rather than Railway's MySQL) because it matches the local stack and OpenEMR is tested against MariaDB.

```powershell
railway add --image mariadb:11.8.8 --service mysql `
  --variables "MARIADB_ROOT_PASSWORD=<MYSQL_ROOT_PASS>"
```

Then attach its volume (`volume add` acts on the linked service):

```powershell
railway service link mysql
railway volume add --mount-path /var/lib/mysql
```

Leave networking private. Don't generate a public domain for the database.

Wait until the service is running before the next step. (It doesn't strictly matter, as OpenEMR retries, but it makes the logs easier to read.)

### 3. Create the OpenEMR service

```powershell
railway add --image openemr/openemr:latest --service openemr `
  --variables "PORT=80" `
  --variables "MYSQL_HOST=mysql.railway.internal" `
  --variables "MYSQL_PORT=3306" `
  --variables "MYSQL_ROOT_PASS=<MYSQL_ROOT_PASS>" `
  --variables "MYSQL_USER=openemr" `
  --variables "MYSQL_PASS=<MYSQL_PASS>" `
  --variables "OE_USER=admin" `
  --variables "OE_PASS=<OE_PASS>" `
  --variables "RAILWAY_HEALTHCHECK_TIMEOUT_SEC=900" `
  --variables "OPENEMR_SETTING_rest_api=1" `
  --variables "OPENEMR_SETTING_rest_fhir_api=1" `
  --variables "OPENEMR_SETTING_rest_system_scopes_api=1" `
  --variables "OPENEMR_SETTING_api_log_option=1" `
  --variables "OPENEMR_SETTING_oauth_password_grant=3"
```

Then generate the public domain:

```powershell
railway service link openemr
railway domain --service openemr --port 80        # prints the generated *.up.railway.app domain
```

**Do not attach a volume at `…/openemr/sites` yet.** A new Railway volume is empty, and mounting it there hides the `sites/default` directory baked into the image, so the container dies on `sqlconf.php: No such file` and crash-loops. Docker named volumes copy image content in on first use; Railway volumes don't. Let the first install run without it, then follow [Persisting `sites/`](#persisting-sites) below.

One setting has no CLI flag: in the dashboard, on the **openemr** service, set **Settings → Deploy → Health check path** to `/meta/health/readyz`.

If the service name for MariaDB isn't `mysql`, change `MYSQL_HOST` to `<name>.railway.internal`.

### 4. Point OAuth at the public URL

OAuth and SMART issuer URLs are generated from this setting, so it has to match the real domain. After the domain exists:

```powershell
railway variable set "OPENEMR_SETTING_site_addr_oath=https://<your-domain>.up.railway.app" --service openemr
railway redeploy --service openemr --yes
```

(Setting a variable triggers a deploy on its own; `redeploy` is belt-and-braces. `railway variable list --service openemr` shows what's set.)

### 5. Watch the first boot

```powershell
railway logs --service openemr
```

The first start runs the database install and takes **5–10 minutes**, ending with `Starting apache!`. The 900-second health-check timeout exists for this.

### 6. Verify

Open `https://<your-domain>.up.railway.app` and sign in as `admin` with your `OE_PASS`.

**Don't trust `/meta/health/readyz`.** It returns HTTP 200 and `"status":"setup_required"` even on a working install (see the root [README](../../README.md)). Signing in is the real check.

### 7. Load sample data

`railway ssh` gives a shell in the container, so the same Synthea import used locally works here:

```powershell
railway ssh --service openemr
# then, inside the container:
. /root/devtoolsLibrary.source && importRandomPatients 50 true
```

The stable image ships `devtoolsLibrary.source` but may not have the `/root/devtools` wrapper the dev image has; if `devtools` exists, `/root/devtools import-random-patients 50` does the same thing. Each patient takes several seconds, so 50 take a while. Synthea downloads a Java runtime on first run, which needs ephemeral disk (100 GB is available).

### 8. Point the test suite at it

```powershell
$env:OPENEMR_BASE_URL = "https://<your-domain>.up.railway.app"
$env:OE_PASS = "<OE_PASS>"
cd ..\..\usecases; .venv\Scripts\python -m pytest
```

**Known gap:** `usecases/conftest.py` runs `db_query()` through `docker compose exec mysql` against the *local* stack, which won't reach Railway. It's used to enable the test OAuth client and by the UC0 dataset tests. To run the suite against Railway, `db_query` needs to go through Railway's TCP proxy (dashboard → mysql → Settings → Networking → TCP Proxy) or `railway connect`. That change isn't made yet.

---

## Custom modules on Railway

The co-pilot module is built into the OpenEMR image, at its normal place under
`interface/modules/custom_modules/`, so it ships with every image and needs no copying. Only its
registration row (`scripts/register_module.py`) and `sites/default/copilot-config.php` live in
the database and on the volume.

Until 2026-09-25 the stock image had no module, so it lived on the sites volume at
`sites/default/copilot-module` and was symlinked in; a redeploy dropped the symlink.

**A fatal in a module bootstrap breaks every page**, login included, because
bootstraps load inside `globals.php`. If the site starts returning 500s after a
module change, disable it first and diagnose afterwards:

```powershell
railway ssh --service openemr-v82 sh -c "mariadb -h mysql-v82.railway.internal -uopenemr -p<pw> openemr -e \"UPDATE modules SET mod_active=0 WHERE mod_directory='oe-module-copilot-agent'\""
```

## Agent service (Clinical Co-Pilot)

The co-pilot's agent runs as a third service built from `Dockerfile.copilot` at the
repository root. It has **no public domain**: OpenEMR reaches it over the private
network and the browser only ever talks to OpenEMR (PRD PHI4). See `ARCHITECTURE.md`
and `copilot/README.md`.

Deployed 2026-09-16 with the steps below (OpenRouter as the model provider).

1. Create the service and set its variables. Generate the shared secret once
   (`python -c "import secrets; print(secrets.token_hex(32))"`) and keep it out of git.
   **Note:** `railway add` echoes every variable it sets, keys included, to the terminal.
   ```powershell
   railway add --service copilot-agent-v82 `
     --variables "PORT=8600" `
     --variables "COPILOT_SHARED_SECRET=<secret>" `
     --variables "COPILOT_PROVIDER=openrouter" `
     --variables "COPILOT_MODEL=anthropic/claude-sonnet-5" `
     --variables "COPILOT_ALLOWED_PROVIDERS=openrouter" `
     --variables "COPILOT_ALLOWED_MODELS=anthropic/claude-sonnet-5" `
     --variables "COPILOT_ALLOWED_ENDPOINTS=https://openrouter.ai/api/v1" `
     --variables "OPENROUTER_API_KEY=<key>" `
     --variables "LANGSMITH_TRACING=true" `
     --variables "LANGSMITH_API_KEY=<key>" `
     --variables "LANGSMITH_PROJECT=openemr-copilot-railway" `
     --variables "COPILOT_TRACE_REDACT=false"
   railway variable set "RAILWAY_DOCKERFILE_PATH=Dockerfile.copilot" --service copilot-agent-v82 --skip-deploys
   ```
   (For Anthropic directly: `COPILOT_PROVIDER=anthropic`, `COPILOT_MODEL=claude-sonnet-5`,
   allowlists to match, and `ANTHROPIC_API_KEY`.)
2. Deploy **from the repository root**. `railway up` uploads the linked directory (the repo),
   so the build context is the root; without `RAILWAY_DOCKERFILE_PATH` Railway's builder finds
   `composer.json` and tries to build OpenEMR instead. `Dockerfile.copilot` lives at the
   root for that reason, with root-relative COPY paths.
   ```powershell
   railway up --service copilot-agent-v82 -c       # streams the build; ends with "Deploy complete"
   ```
   Do **not** generate a public domain for this service. Check readiness from the openemr
   container over the private network:
   ```powershell
   railway ssh --service openemr-v82 sh -c "curl -s http://copilot-agent-v82.railway.internal:8600/readyz"
   ```
   It is 503 until the model key and secret are set (fail closed).
3. Point OpenEMR at it without redeploying it: write the config onto the persistent volume.
   ```powershell
   $cfg = @"
   <?php
   return [
       'COPILOT_AGENT_URL' => 'http://copilot-agent-v82.railway.internal:8600',
       'COPILOT_SHARED_SECRET' => '<same secret>',
   ];
   "@
   $cfg | railway ssh --service openemr-v82 sh -c "cat > /var/www/localhost/htdocs/openemr/sites/default/copilot-config.php && chown apache:apache /var/www/localhost/htdocs/openemr/sites/default/copilot-config.php && chmod 640 /var/www/localhost/htdocs/openemr/sites/default/copilot-config.php"
   ```
   Variables on the openemr service (`COPILOT_AGENT_URL`, `COPILOT_SHARED_SECRET`) work too and
   win over the file, but setting them triggers a redeploy.
4. The module itself ships inside the OpenEMR image ("Building from this checkout").
5. Book today's rounding list (five appointments per doctor) before a demo. The list is for
   the **server's** date (UTC), which the script uses by default:
   ```powershell
   cd usecases
   $env:OPENEMR_BASE_URL="https://<app>.up.railway.app"; $env:OE_PASS="<admin pw>"
   $env:OE_DB_VIA="railway"; $env:OE_DB_PASS="<openemr db pw>"
   .venv\Scripts\python ..\scripts\seed_appointments.py
   ```
6. Sign in as `doctor1` or `doctor2` and open the **CopilotAgent** tab. `admin` is denied it by
   design and the denial is written to the audit log; an administrator gets a **CopilotHealth**
   tab instead, showing the service's counters since it last started. Traces appear in the LangSmith project
   named in `LANGSMITH_PROJECT`.

`COPILOT_TRACE_REDACT=true` hides prompts and outputs in LangSmith; use it whenever the data
is not synthetic (AUDIT.md C4b).

## Nightly rounding-list seeding (cron)

The co-pilot's list is *today's* appointments, so it empties at midnight. A third service,
`copilot-seeder`, rebooks it every night. It is a one-shot container: it seeds, prints a
verification table and exits, which is what Railway's cron scheduler expects.

Set up 2026-09-16. It runs at **01:05 UTC**, shortly after the server's date rolls over, and
each run books `SEED_DAYS` days starting from that new date, so a missed night self-heals.

```powershell
railway add --service copilot-seeder-v82          # choose "Empty Service"
# Set variables individually: `railway add --variables` echoes values to the terminal.
railway variable set "RAILWAY_DOCKERFILE_PATH=Dockerfile.seeder" --service copilot-seeder-v82 --skip-deploys
railway variable set "OE_DB_VIA=mysql"        --service copilot-seeder-v82 --skip-deploys
railway variable set "MYSQL_HOST=mysql-v82.railway.internal" --service copilot-seeder-v82 --skip-deploys
railway variable set "MYSQL_PORT=3306"        --service copilot-seeder-v82 --skip-deploys
railway variable set "MYSQL_USER=openemr"     --service copilot-seeder-v82 --skip-deploys
railway variable set "MYSQL_DATABASE=openemr" --service copilot-seeder-v82 --skip-deploys
railway variable set "MYSQL_PASSWORD=<openemr db pw>" --service copilot-seeder-v82 --skip-deploys
railway variable set "OPENEMR_BASE_URL=https://<app>.up.railway.app" --service copilot-seeder-v82 --skip-deploys
railway variable set "OE_USER=admin"          --service copilot-seeder-v82 --skip-deploys
railway variable set "OE_PASS=<admin pw>"     --service copilot-seeder-v82 --skip-deploys
railway variable set "SEED_DAYS=5"            --service copilot-seeder-v82 --skip-deploys
railway variable set "SEED_PER_DOCTOR=5"      --service copilot-seeder-v82 --skip-deploys
railway up --service copilot-seeder-v82 -c        # builds Dockerfile.seeder from the repo root
```

Then attach the schedule. The CLI has no cron flag, so use the GraphQL API with the
service's own id (`railway variable list --service copilot-seeder-v82 --json` shows
`RAILWAY_SERVICE_ID` and `RAILWAY_ENVIRONMENT_ID`):

```powershell
railway api 'mutation SetCron($serviceId: String!, $environmentId: String, $input: ServiceInstanceUpdateInput!) { serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input) }' --variables '{\"serviceId\":\"<service id>\",\"environmentId\":\"<environment id>\",\"input\":{\"cronSchedule\":\"5 1 * * *\"}}'
```

**Redeploy after setting the schedule.** The mutation changes the service setting but does
not create a deployment, so the deployment `railway up` already made keeps
`cronSchedule: null` in its manifest. The dashboard then renders the service as always-on,
a green `Running` with a climbing uptime timer, even though every run exits in about eight
seconds. The CLI is unaffected: `railway status` reads the instance state and correctly says
`Completed`, so the two disagree and the card looks like a hung job. Redeploy, or set the
schedule to a *different* value, so a fresh manifest captures it. Re-applying an identical
value deploys nothing, because Railway needs a real diff. A correctly registered cron
service reads `Online - 0/1 running`.

Read it back, including when it next fires:

```powershell
railway api 'query Check($serviceId: String!, $environmentId: String!) { serviceInstance(serviceId: $serviceId, environmentId: $environmentId) { cronSchedule nextCronRunAt } }' --variables '{\"serviceId\":\"<service id>\",\"environmentId\":\"<environment id>\"}'
```

Notes:

- The container reaches MariaDB directly over the private network (`OE_DB_VIA=mysql`),
  because `railway ssh` needs the CLI and a login that a container does not have. Railway's
  private network is IPv6 and takes a moment to come up, so the connection retries briefly.
- Appointments are still written through the REST API, so validation and audit logging run
  (AUDIT.md C1b). Only the reads and the cleanup of its own previous bookings use SQL.
- `railway logs --service copilot-seeder-v82` shows the last run's verification table. Logs are
  scoped to the *current* deployment, so after a redeploy they stay empty until the next
  scheduled run fires.
- To tell a stalled run from a mislabelled card, read the meter rather than the dashboard:
  `railway metrics --service copilot-seeder-v82` (0 vCPU means nothing is running) or
  `railway ssh --service copilot-seeder-v82 ps` (`status: exited`). The script has no overall
  wall-clock timeout, so a genuine stall is possible and looks identical on the card.
- To seed a different window, change `SEED_DAYS`; to pause it, set `cronSchedule` to `null`.

## Cost control between demos

- **Pause:** in the dashboard, remove the deployment or scale the service to zero replicas. Volumes keep their data and cost $0.15/GB/month.
- **Resume:** redeploy the service; the volume reattaches with the database intact.
- **Watch:** Project → Usage shows the running total against the included $5.

---

## Gotchas

| Symptom | Cause and fix |
|---|---|
| "Application failed to respond" | The target port doesn't match `PORT`. Both must be 80. |
| Redirect loop, or certificate errors | `DOMAIN` got set, so the image tried Let's Encrypt. Remove the variable and redeploy. |
| Deploy marked failed while the logs still look busy | The install ran past the health-check timeout. Confirm `RAILWAY_HEALTHCHECK_TIMEOUT_SEC=900`. |
| OpenEMR can't reach the database | The host must be `<service>.railway.internal`, and private networking is IPv6-based. If the client can't connect, use the TCP proxy host and port from the dashboard instead. |
| Permission errors writing to the volume | Railway's note on non-root images. Set `RAILWAY_RUN_UID=0` on the service. |
| Data vanished after a redeploy | Something is writing outside the volume. Only `sites/` is persisted; the database lives on the mysql service's volume. |
| Crash loop with `sqlconf.php: No such file` and `Plan to try an upgrade from 0 to 9` | An empty volume is mounted over `…/openemr/sites`, hiding the image's `sites/default`. Detach it, let the install run, then populate the volume as in [Persisting `sites/`](#persisting-sites). |
| `railway ssh` or `railway volume files` fails with "container is not running" or an SFTP timeout | Both need a **running** container. Fix the deploy first; volume files can only be managed while some service holding that volume is up. |

---

## Persisting `sites/`

> **Historical.** With the image built from this checkout, `SWARM_MODE=yes` on the first boot
> fills an empty volume by itself ("Current deployment" above). This was the manual procedure for
> the stock image.

`sites/default` holds the site config (`sqlconf.php`), uploaded documents, LBF layouts and the OAuth keys generated on first API use. Without a volume it's recreated on every deploy, so anything written there is lost.

Because a fresh Railway volume is empty, it must be populated **after** the install, with the *configured* `sites/` (the one whose `sqlconf.php` has `$config = 1`), not the blank copy from the image:

1. Install first with no volume attached, and confirm you can sign in.
2. Copy the configured directory out of the running container:
   ```powershell
   railway service files download /var/www/localhost/htdocs/openemr/sites ./sites --service openemr
   ```
3. Attach the volume to a small helper service that stays running (the app can't hold it while crash-looping), upload into it, then detach:
   ```powershell
   railway add --image nginx:alpine --service seeder
   railway service link seeder
   railway volume attach -v openemr-volume -y
   railway volume files -v openemr-volume upload ./sites/ /
   railway volume detach -v openemr-volume -y
   ```
4. Attach it to OpenEMR at the mount path and redeploy:
   ```powershell
   railway service link openemr
   railway volume attach -v openemr-volume -y     # mount path /var/www/localhost/htdocs/openemr/sites
   railway redeploy --service openemr --yes
   ```
5. **Fix ownership.** Files uploaded over SFTP land owned by `root`, but PHP runs as `apache`, so the app returns HTTP 500 with `PHP Fatal error: Directory ".../documents/smarty/gacl" was not created` in the logs. Once the container is running:
   ```powershell
   railway ssh --service openemr "chown -R apache:apache /var/www/localhost/htdocs/openemr/sites && chmod 700 /var/www/localhost/htdocs/openemr/sites/default/documents"
   ```
   No redeploy needed; the next request succeeds.
6. Delete the helper service: `railway service delete seeder --yes`.

If you skip this, the deployment still works and patient data is safe (it lives in MariaDB's volume), but documents and OAuth keys are lost on each redeploy.

---

## Security notes for this deployment

Carried over from [AUDIT.md](../../AUDIT.md):

- **The OAuth password grant is on** (S1), because the test suite and the agent need it. Turn it off (`OPENEMR_SETTING_oauth_password_grant=0`) once SMART authorization-code login is in place.
- **API logging is minimal** (`api_log_option=1`), so full PHI bodies aren't stored (S7).
- **No phpMyAdmin, no exposed database port, no Xdebug**, unlike the dev stack (S8).
- **The database isn't encrypted at rest** by the application (S11), so this holds synthetic data only.
- **The admin password** replaces the default `pass`. Rotate it if it's ever shared.

## Week 2 notes

- New agent variables: `COPILOT_VISION_MODEL`, `COPILOT_VISION_RATE_LIMIT_RETRIES`, `COPILOT_EMBED_MODEL`,
  `COPILOT_RERANK` (root README, "Week 2"). All optional; the vision model must be on the allowlist.
- `Dockerfile.copilot` installs the CPU-only torch wheel before the requirements and prefetches the
  two retrieval models at build, so the image grows by roughly 400 MB and a cold start downloads
  nothing. The first build after this change is slower.
- The module gained `public/patient.php` and new `api.php` actions (`attach`, `extract`, `documents`,
  `supervise`, `page`); ship the whole module directory as before.
- The publish gate is unchanged: `copilot/check_local.ps1` (which now runs the Week 2 eval gate)
  then `deploy_agent.ps1`.

### Week 2 was published on 2026-09-23, from `week2` at `c62aced`

Local checks first: 185 unit tests, the 74-case gate, the UI guard, and the live golden suite 9/9.

Agent variables set before the deploy, because the code alone would have failed closed -- the
allowlist is a real control and `gemini` was not on it:

| Variable | Set to |
|---|---|
| `COPILOT_MODEL` | `google/gemini-2.5-flash-lite` |
| `COPILOT_VISION_MODEL` | `google/gemini-2.5-flash-lite` |
| `COPILOT_ALLOWED_MODELS` | gemini and sonnet added, the two `:free` slugs kept |
| `COPILOT_VISION_RATE_LIMIT_RETRIES` | `1` |
| `COPILOT_TOPIC_CHECK` | `true` |

Then `railway up --service copilot-agent -c`, then the module to the sites volume, then
`COPILOT_DEMO_TOOLS` in `sites/default/copilot-config.php` so a grader can generate a document to
ingest. Order matters: the agent first, because the new module calls `supervise` and the old agent
has no such endpoint.

**Shipping the module was a script:** `deploy_module.ps1`, since replaced by `preflight_module.ps1` (the module now ships in the image)
(`-CheckOnly` to preflight and ship nothing). It reads the module's OpenEMR dependencies, checks
them on the target, ships with a pre-swap guard, and re-checks what it installed. 62 checks.

**Ship the module with a check before the swap.** The tar goes over `railway ssh` as base64 and is
unpacked into `copilot-module.new`; only if `openemr.bootstrap.php`, `public/api.php`,
`public/patient.php`, `public/demo.php` and `src/DocumentWriter.php` are all present does it become
`copilot-module`. Without that test a truncated transfer replaces the live module with an empty
directory, and the swap is one `mv` -- there is nothing to notice before the site is broken.

**Do not edit `copilot-config.php` with `sed` through `railway ssh`.** Quoting does not survive the
shell layers: `'` arrived literally and produced `x27COPILOT_DEMO_TOOLSx27 => '1'`, a bareword
constant. `php -l` reports **no syntax errors** on that, because an undefined constant is a runtime
error, not a parse error -- so the usual check passes on a file that throws on include. Pipe the new
line in on stdin instead, rebuild the file with `head -n -1`, and verify by actually including it:

```sh
php -r '$c = include "/tmp/cfg.new"; echo implode(",", array_keys($c));'
```

Verified after the deploy: `/readyz` reports `ready: true` with both models approved by the
allowlist, the module's four pages return 200, and an unauthenticated `api.php` answers
"Site ID is missing from session data!" rather than leaking a chart.

### Run deploy checks as the web server user, not as root

`railway ssh` lands as **root**, and root can write where apache cannot. The first version of the
preflight reported the read-only web root as writable *and created it* -- which is worse than no
check, because the module then resolves to a root-owned directory and fails to write into it. It
had to be undone by hand.

Anything that asks "can the app do X" has to ask as the app:

```sh
su -s /bin/sh apache -c "php /tmp/check.php"
```

The same caution applies to `chown` after any hand-run copy. `preflight_module.ps1` does this for you.

### Two PowerShell traps on the way to `railway ssh`

Both cost an hour and neither produces an obvious error:

- **stderr is not failure.** The CLI prints `Using SSH key from file ...` on stderr; with
  `$ErrorActionPreference = "Stop"`, PowerShell 5.1 turns that into a `NativeCommandError` and
  kills the script although the command *succeeded*. Run native calls with `Continue` and judge
  them on `$LASTEXITCODE`.
- **A pipe adds a byte-order mark.** Piping a here-string into the CLI prefixes the stream with a
  UTF-8 BOM -- the CLI is an npm PowerShell shim, so `$OutputEncoding` never reaches it -- and
  `sh` then reports `cat: not found` for a line that plainly says `cat`. Base64 input corrupts the
  same way, silently. Write the script to a file (LF, no BOM) and redirect it with
  `cmd /c "railway ssh ... sh < file"`.

## Where the pipeline runs

**A project runner, in Docker, on the maintainer's machine.** Not a shared runner, and not a cloud
one.

This GitLab has a shared instance runner and it could not be used: instance runners are off per
project, and the toggle would not stay on. With it off, every job failed in **00:00:00** -- created,
picked up by nobody, and no log to read, which is the least informative failure GitLab produces. The
fix was to stop depending on someone else's runner.

```powershell
docker run -d --name gitlab-runner --restart always `
  -v gitlab-runner-config:/etc/gitlab-runner `
  -v /var/run/docker.sock:/var/run/docker.sock `
  gitlab/gitlab-runner:latest

docker exec gitlab-runner gitlab-runner register --non-interactive `
  --url https://labs.gauntletai.com --token <glrt-... from Settings -> CI/CD -> Runners> `
  --executor docker --docker-image alpine:latest
```

Two settings that are easy to get wrong:

- **Tick "Run untagged jobs"** when creating the runner in the UI. The jobs in `.gitlab-ci.yml`
  carry no tags, and a runner that only accepts tagged ones leaves them stuck exactly as the
  instance runner did.
- **Raise concurrency.** The default is one job at a time, so the four jobs queue single-file.
  `concurrent = 4` and `request_concurrency = 4` in `/etc/gitlab-runner/config.toml` run them
  together: about two minutes wall-clock instead of six. Restart the container after editing --
  and not while a job is running, which kills it mid-flight.

**What this means in practice.** `--restart always` brings the runner back with Docker Desktop, so
there is nothing to start by hand. But **pipelines only run while that machine is up**. A push made
while it is off creates a pipeline that sits pending until it returns.

**Nothing about reviewing this repository depends on that.** The eval gate needs no runner, no API
key and no network:

```
cd copilot && python -m evals.stage2.gate
```

CI is a second place the same gate runs, and the place a *merge* is blocked -- not the only place it
can be checked. Moving the runner somewhere always-on is the fix if that ever matters; it is a
different host for the same two commands.

---

## CI/CD (GitLab) -- tests live, deploy parked

> **The test half runs.** `.gitlab-ci.yml` at the repository root runs the unit tests, the
> 76-case eval gate, the UI guard and a PHP syntax check on every push and every merge request.
> It holds no secrets, needs no API key and cannot reach Railway. A regression fails the
> pipeline, which is what stops it reaching the demo.
>
> **The deploy half is parked**, at `deploy/railway/gitlab-ci.yml`, out of the root where GitLab
> never reads it. Publishing stays a deliberate, human-approved act; a pipeline that could deploy
> would quietly remove that.
>
> **Outstanding before the deploy half can be switched on:**
> 1. Add `RAILWAY_TOKEN` as a masked, protected CI/CD variable (step 2 below).
> 2. Append `deploy` to `stages:` in the root file and paste in the two jobs.
> 3. Run them once by hand and fix what the first real run shows -- **they have never been
>    executed**. The test jobs run clean; the deploy jobs have not, because they need the token.
> 4. Keep `when: manual`.
>
> **A note on the runner**, because it cost a day. This GitLab has one shared instance runner,
> but *instance runners are off per project by default*. With the toggle off, every job fails in
> 00:00:00 -- created, never picked up, no log worth reading. If a pipeline here ever fails
> instantly across all jobs at once, check **Settings -> CI/CD -> Runners -> Instance** before
> reading anything else.
>
> The pre-push hook (`copilot/hooks/pre-push`) still runs the same three checks locally, so a
> regression is caught before it is pushed as well as after.

The pipeline runs the checks on every push and merge request, and would put deployment behind a
button rather than behind a merge.

**Tests** need no key, no network and no model: unit tests, the 76-case eval gate, the UI guard
and `php -l` over the module. They run in `python:3.13-slim` against `copilot/requirements-ci.txt`,
which is `requirements.txt` without torch and sentence-transformers -- the gate forces
`embed_model=none`, and those imports are lazy, so CI installs neither. Verified in a clean
container: whole suite, gate and guard green without them.

**Deploy is `when: manual`, and that is the point.** Nothing here has ever published to Railway
without a person approving that specific change; a pipeline that deployed on merge would remove
that quietly. The two jobs are the same two steps as the local scripts -- `railway up` for the
agent image, then the module tar over `railway ssh` -- with the typed DEPLOY replaced by pressing
play on a protected branch. Turning them into `when: on_success` trades the gate away; that is a
decision, not a setting.

### Setting it up

1. **A runner.** Already done for the test jobs -- see
   [Where the pipeline runs](#where-the-pipeline-runs) below. The deploy jobs would use the same
   one. To register another, with a Docker executor on any machine that can reach the GitLab host:

   ```bash
   docker run -d --name gitlab-runner --restart always      -v /srv/gitlab-runner/config:/etc/gitlab-runner      -v /var/run/docker.sock:/var/run/docker.sock      gitlab/gitlab-runner:latest

   docker exec -it gitlab-runner gitlab-runner register      --non-interactive --executor docker --docker-image alpine:3      --url https://labs.gauntletai.com/ --token <runner token from the project's Runners page>      --description "openemragent docker"
   ```

   The jobs pin their own images, so `--docker-image` is only the fallback.

2. **The token.** *Settings -> CI/CD -> Variables*, add `RAILWAY_TOKEN` (a Railway **project**
   token for `openemr-agent`), **Masked** and **Protected**. Protected keeps it off feature
   branches, which is why the deploy jobs only offer themselves on `main` and `week2`.

3. Push. The test jobs run; the deploy jobs wait for a click.

Railway service variables (`OPENROUTER_API_KEY`, `COPILOT_SHARED_SECRET`, `COPILOT_MODEL`, ...)
stay in Railway. CI builds and ships the image; it never runs the service, so it never needs them.
