# Deploying OpenEMR to Railway

Public deployment of this fork, reachable over HTTPS at a `*.up.railway.app` address.

**Synthetic data only.** This deployment is on the public internet with the OAuth password grant enabled. Never load real patient data into it (see [AUDIT.md](../../AUDIT.md) §5).

**Cost:** the Hobby plan is $5/month including $5 of usage, then about $20/vCPU/month and $10/GB RAM/month, metered per minute, plus $0.15/GB/month for volumes. Two always-on services land around $15–25/month. Remove or scale the services to zero between demos and you pay for little more than the volumes.

---

## How this differs from the local stack

| | Local (`docker/development-easy`) | Railway |
|---|---|---|
| Image | `openemr/openemr:flex` (dev) | `openemr/openemr:latest` (stable, digest-pinned) |
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
