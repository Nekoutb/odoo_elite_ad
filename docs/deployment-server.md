# Deployment — the self-hosted Odoo 19 Community server

Since 11/10/2026 the target is a server Elite Advisors rents, not Odoo.sh
(`docs/deployment-odoo-sh.md` describes the platform being left). Nothing
secret is written here: passwords live on the server, in files only root
reads.

## The machine

| Item | Value |
|---|---|
| Provider, plan | Vultr, High Performance AMD, 4 vCPU / 12 GB / 260 GB NVMe, Paris |
| OS | Ubuntu 24.04 LTS, Docker CE, Caddy 2 |
| Names | `elimelecodoo.com` (production), `staging.` and `dev.` (Odoo's own login, no extra gate) |
| Access | SSH, keys only, port 22; firewall opens 22, 80, 443 |
| Backups | Vultr automatic daily images, plus the server's own dumps (step 4 of the plan) |

## Layout: `/opt/elimelec`

```
caddy/      Caddyfile + compose: HTTPS front door, /websocket -> 8072
prod/       compose, odoo.conf, repo/ (branch prod),    db elimelec
staging/    compose, odoo.conf, repo/ (branch staging), db elimelec_staging
dev/        compose, odoo.conf, repo/ (branch staging), db elimelec_dev
oca/        OCA 19.0 clones, mounted read-only at /mnt/oca in every stack
backups/    restored dumps (never in the repository: client data)
bin/        deploy.sh, sql.sh, the cutover scripts
```

Each environment is one compose project: `postgres:16` + `odoo:19`, the
Odoo container named `<env>-odoo` on the shared docker network `web` that
Caddy routes to. `odoo.conf` carries `proxy_mode`, `workers` (2 on
production, 1 elsewhere), `list_db = False` and the addons path: the
repository's `addons/` first, then the OCA repositories.

## The overview page

`https://status.elimelecodoo.com`, behind the gate: the three environments
side by side (state, branch and commit, last test run on that branch,
module versions, database size, last deploy), the backups (last daily,
hourly and restore test with their results, what is in the bucket) and
the server (uptime, load, memory, disk, containers). Rendered by
`bin/status-page.py` every five minutes and after each deploy, into
`/opt/elimelec/status/index.html`, which Caddy serves as files.

### The buttons on the overview page

Connect opens the environment. Rebuild, Deploy to dev, Promote and
Backup now post to `/actions/*` of the status site, which the gate
protects and a small service on the host answers
(`bin/actions-server.py`, systemd unit `elimelec-actions`, port 8070 open
to the containers only). Each button runs one of the scripts below and
streams its output; one action at a time. Promotion pushes from a
control clone at `/opt/elimelec/control/repo` with the server's deploy
key (`/root/.ssh/elimelec_deploy`, added to the repository's deploy keys
with write access) and is refused unless the source branch's last test
run is green and the push is a fast-forward; production is promoted from
staging only.

## Deploying

```
ssh elimelec-prod bash /opt/elimelec/bin/deploy.sh staging
ssh elimelec-prod bash /opt/elimelec/bin/deploy.sh dev staging   # switch dev's clone to a branch first
ssh elimelec-prod bash /opt/elimelec/bin/deploy.sh prod          # on the owner's word only
```

The script pulls the environment's branch (fast-forward only), runs
`-i elite_finance -u elite_clearance,elite_finance` on its database and
restarts the stack. It refuses to deploy production from any branch but
`prod`. The rule from Odoo.sh survives unchanged: build on `dev/**`, CI
green, fast-forward `staging`, deploy to the staging stack, the owner
checks, then `git push origin staging:prod` and `deploy.sh prod`.

## Leaving Enterprise: the cutover procedure

Rehearsed on staging on 11/10/2026 with the production backup of 10/10.
The order matters.

1. **Freeze** the team, download the *exact* backup (zip with filestore)
   from the Odoo.sh console, copy it to `/opt/elimelec/backups/`.
2. **Restore** into the production database (`bin/srv8_restore.sh` is the
   model): create the database, `psql < dump.sql`, copy the filestore into
   the data volume under the database's name, owned by uid 100.
3. **Upgrade the module** to the version the clone carries:
   `odoo -d elimelec -u elite_clearance --stop-after-init`. Production's
   data is at an older version than the code; this is the ordinary staging
   situation and runs the migrations.
4. **Uninstall the Enterprise modules** through Odoo's own uninstall
   (`bin/uninstall_enterprise.py` in `odoo shell`): every module whose
   licence starts with `OEEL`. The script refuses if the Clearance
   application or its dependencies would be touched. Odoo may leave an
   empty access group it could not delete; harmless.
5. **Update every installed module**: `-u all`. Enterprise's accounting
   module had re-parented Dashboard, Customers, Vendors, Accounting,
   Review, Reporting and Configuration under its own root; deleting that
   root left them floating at the top level beside the apps, with Finance
   empty. `-u all` rewrites every core record to its Community definition,
   and the Clearance module, loaded last, re-applies "Finance".
6. **Install the OCA modules and the Finance module**:
   `-i date_range,report_xlsx,account_financial_report,mis_builder,mis_builder_budget,account_statement_base,account_reconcile_oca,account_statement_import_file,account_statement_import_camt,account_statement_import_file_reconcile_oca,elite_finance`.
7. **Start** the stack, re-point `elimelecodoo.com` if not already, log in
   as administrator (sets the base URL), key the outgoing mail server,
   walk the smoke test of `docs/lab-setup.md`.
8. **Unfreeze.** Cancel Odoo.sh after a clean week.

The staging rehearsal of steps 2–6 took under fifteen minutes.

## Staging and dev

Staging is a copy of production, refreshed from a backup, neutralised by
Odoo (`odoo neutralize`, or the "test" backup Odoo.sh produces): no mail,
no scheduled jobs. Dev is an empty database with demo data. Both are
reached with Odoo's own login and nothing else (owner, 11/10/2026); the
front door's basic-auth gate (`caddy/.gate` on the server) protects only
the overview page's action buttons.


## The client's UAT page: elimelecodoo.com/uat

The UAT script (UAT-CL-01, French at `/uat/`, English at `/uat/en.html`,
both as PDF) is served by Caddy from `/opt/elimelec/uat` on the
production site, with the team's setup section left out. A tester types
their name once; every Pass / Fail / N/A and note is sent to
`bin/uat-server.py` (`/uat/api/*`, port 8071, systemd `elimelec-uat`),
which keeps `/opt/elimelec/uat/results.json` and a line per change in
`results.log`. `/uat/progress.html` shows every tester's progress and
the failed cases with their notes. To publish a new version of the
script: build the pages, copy them and `uat_img/` over, nothing to
restart. The results file is included in the server config backup.
