# Local lab — Odoo 19 Community

The lab is disposable. It exists to exercise `addons/elite_clearance` before
anything reaches Odoo.sh. Nothing in `docker/` or `docker-compose.yml` is
production configuration.

## One-time setup

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/),
   accept the WSL 2 defaults, reboot if asked, and wait for the whale icon to
   stop animating.
2. From this folder:

   ```bash
   docker compose up -d
   ```

   The first run pulls roughly 2 GB (Odoo 19 + PostgreSQL 16). Later starts
   take seconds.

## Create the database

Open <http://localhost:8069>. On the *Create Database* form:

| Field | Value |
|---|---|
| Master Password | `elite_lab` (set in `docker/odoo.conf`) |
| Database Name | `clearance_dev` |
| Email / Password | your own login for the lab |
| Demo data | tick it — the sample service types load |

Then: *Settings → Activate the developer mode*, *Apps → Update Apps List*,
clear the **Apps** filter tag in the search box, search `Clearance`, and
activate **Clearance Files**.

Installing runs the post-install hook, which seeds Elite Advisors' real
master data: 23 document types, the four service types (IM, BO, ES, AI) with
their checklists, and 21 expense categories. The demo records are separate
and carry `DEMO-` prefixed codes so they never collide with the real ones.

## Before you can post anything

*Clearance → Configuration → Settings* (or *Settings → Clearance*) needs four
accounts and a journal before expenses will settle:

- **Out-of-Pocket Expenses Account** — balance sheet, asset, reconcilable.
- **Employee Advances Account** — balance sheet, asset, reconcilable.
- **Clearance Fee Income Account** — income.
- **Miscellaneous Journal** — general, used for advance justifications.
- **Sales Journal** — optional; the first sales journal is used if empty.

Settlement journals (Cash, Bank, Mobile Money, Maviance) are ordinary
`cash`/`bank` journals created under *Invoicing → Configuration → Journals*.

## Smoke test

1. *Clearance → Files → Clearance Files → New*.
2. Any client, service type **Import** — the checklist fills itself. Save.
3. **Start Work** → refused, mandatory documents missing. That is the gate
   working.
4. Write a justification, **Request Waiver**, then **Approve Waiver**.
5. **Start Work** now succeeds.
6. Add an expense, submit, approve, settle — check the journal entry debits
   the out-of-pocket account.
7. **Close for Operations**, **Create Invoice**, post it, **Mark Complete**.

Repeat step 1–5 logged in as a user holding *Clearance / User* only. Unit
tests run as admin and will not catch an access-rights failure.

## Everyday commands

```bash
docker compose up -d          # start
docker compose down           # stop, keep the data volumes
docker compose logs -f odoo   # follow the server log
docker compose restart odoo   # reload Python code
```

XML, view and schema changes additionally need *Apps → Clearance Files →
Upgrade* (or a `-u elite_clearance` run).

Run the test suite against a throwaway database:

```bash
docker compose run --rm odoo odoo -d clr_test -i elite_clearance --with-demo --test-enable --test-tags /elite_clearance --stop-after-init
```

## When the module does not appear in Apps

- Clear the **Apps** filter tag in the search box.
- Run *Update Apps List* in developer mode.
- `addons/elite_clearance/__manifest__.py` must exist at exactly that depth.
- Check `docker compose logs odoo` for a load error — a malformed view stops
  the whole module from installing.

## Known lab limitations

- Community edition: the menu is **Invoicing**, and there are no Trial
  Balance or P&L reports. Those are Enterprise (or OCA
  `account_financial_report`) territory.
- The lab chart of accounts may be Generic. Production must load `l10n_cm`
  (SYSCOHADA) **first**.
