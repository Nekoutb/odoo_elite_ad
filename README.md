# Elite Advisors — Clearance Files (Odoo 19)

Odoo 19 module that runs a customs clearance and logistics services business
as job files: one file per clearance instruction, with a documentation gate,
out-of-pocket disbursements, employee cash advances, and client recharge
billing that clears the balance sheet.

| | |
|---|---|
| Module | `addons/elite_clearance` |
| Version | `19.0.9.0.0` |
| Odoo | 19.0 Community (lab) / 19.0 Enterprise (production, Odoo.sh) |
| Licence | LGPL-3 |
| Currency / locale | XAF, Cameroon (SYSCOHADA — `l10n_cm`) |

---

## What it does

**`logistics.file` — the clearance job file.**
`draft → in_progress → ops_closed → done`, plus `cancel`. Every file creates
its own analytic account under the *Clearance Files* plan at creation, and
every posting the module makes carries that account. Per-file profitability
therefore falls out of the accounting rather than out of a spreadsheet.

**The documentation gate.** Each `logistics.service.type` carries a checklist
template. Opening a file generates the checklist; `action_start_work` refuses
while a mandatory document is missing, unless an approver signs a waiver with
a written justification, which is posted to the chatter. Ticking documents
stamps one shared transaction timestamp (`env.cr.now()`) across everything
saved together; the *Set Received Date/Time* wizard back-dates in bulk.

**`logistics.expense` — out-of-pocket disbursements.**
`draft → submitted → approved → settlement_approved → settled`, and for
advances a further `justified` step that requires at least one attachment.
Each step is a different pair of hands:

| Step | Who |
|---|---|
| Key and submit | Operations, Customer Service or Transit team — **never Finance** |
| Approve | Operations, Customer Service or Transit **Manager** |
| Set how it is paid (mode, vendor, holder, journal) | Finance — the originator cannot even see these fields |
| Sign the settlement | Finance **Manager** |
| Settle, justify, bill | Finance |
| Close the file for operations | Operations **Manager**, and only once the customs fee is keyed |

| Step | Debit | Credit |
|---|---|---|
| Settle, paid direct | 47xx Débours engagés | Cash / bank / mobile money journal |
| Settle, via advance | 421101 Personnel débours avancés | Cash / bank / mobile money journal |
| Justify an advance | 47xx Débours engagés | 421101 Personnel débours avancés |

**Staff advances.** An advance must name a registered employee. It is carried
on a single account — 421101 — with that person's work contact as the
*auxiliary*, which is Odoo's native subsidiary-ledger mechanism: there is no
per-employee account in the chart, and each person's ledger and balance come
from the Partner Ledger on 421101. Because hr only creates that contact as a
side effect of writing a work e-mail or phone, the module creates it when the
employee is created.

An unjustified advance is the staff member's debt, not a client disbursement.
The justification entry is the reclassification from 421101 to 47xx, and it is
the *only* thing that makes a disbursement billable — nothing outside 47xx is
ever invoiced.

**The unjustified-advance gate.** A file carrying an unjustified advance
cannot be closed for operations or billed. An **Operations Manager** — a
separate group from the Manager who approved the expense and the Finance user
who paid it — may waive that with a written explanation. The waiver releases
the file, never the money: the unsupported amount is not recharged to the
client, stays on 421101 against the holder, and remains recoverable from
them.

**Billing.** From `ops_closed`, `action_create_invoice` raises a customer
invoice with two sections: disbursements recharged at cost against the
out-of-pocket account (clearing it, and carrying no tax — they are the
client's own liability paid on their behalf), then the fee lines, which do
carry the default taxes: the commission (`service_type.commission_rate` % of
the out-of-pocket total) and the manually keyed customs service fee, as two
separate lines. Invoice references are structured per service type
(`EL26IM0001`); file references likewise (`2026IM0009`).

A file cannot be marked complete until that invoice is posted. Reopening a
closed file goes through a wizard that demands a manager and a written reason.

**Approvals.** Every checkpoint — documentation waiver, expense approval,
settlement approval, disbursement, billing, operations close, unjustified-
advance waiver — takes an explicit list of users under *Settings → Clearance*.
Where no list is configured the security groups above apply.

## Legacy data (Elimelec / Teese)

`addons/elite_clearance_teese` is a one-off importer for the Teese warehouse
export: upload the zip on *Clearance → Configuration → Teese Legacy Import*.
It is record-keeping only — legacy invoices arrive as **draft** customer
invoices that a server-side guard refuses to post, and nothing is posted;
the balances arrive as a trial balance at the 31/08/2026 cutoff. It is idempotent and never puts
the data in this repository. The mapping,
every judgement call and the reconciliation figures are in
[docs/legacy-migration-teese.md](docs/legacy-migration-teese.md). Uninstall
it after go-live; the fields it needs live in `elite_clearance`.

## Repository layout

```
addons/elite_clearance/     the deliverable — the only thing that ships
addons/elite_clearance_teese/  one-off legacy importer; uninstall after go-live
  models/                   persistent models
  wizard/                   TransientModels and their views
  views/                    list / form / kanban / search / settings / menus
  security/                 groups, model access, record rules
  data/                     sequences, the analytic plan
  demo/                     lab sample data (DEMO- prefixed codes)
  migrations/<version>/     pre- / post- / end- upgrade scripts
  tests/                    the suite CI runs on every push
  static/description/       app icon and store page
docker/                     lab server config
docs/                       lab setup, Odoo.sh deployment
tools/                      repo checks used by CI
.github/workflows/          CI
```

Everything outside `addons/` is scaffolding and never reaches production.

## Working on it

```bash
docker compose up -d
```

Then http://localhost:8069 — full walkthrough in [docs/lab-setup.md](docs/lab-setup.md).

Apply changes: `docker compose restart odoo` picks up Python; XML and schema
changes additionally need *Apps → Clearance Files → Upgrade*.

Run the suite against a throwaway database:

```bash
docker compose run --rm odoo odoo -d clr_test -i elite_clearance --with-demo --test-enable --test-tags /elite_clearance --stop-after-init
```

CI runs exactly that on every push. Before calling anything done: the suite
must be green **and** the path must be exercised in the browser as a
restricted user (Clearance / User only) — unit tests run as admin and miss
access-rights failures.

## Deploying

Odoo.sh, 19.0, Enterprise. See [docs/deployment-odoo-sh.md](docs/deployment-odoo-sh.md).
The chart of accounts (`l10n_cm`, SYSCOHADA) must be installed **before** this
module on a production database.

## Conventions

- Never edit Odoo core.
- Bump the manifest version on any schema change; upgrade scripts go under
  `migrations/<version>/`.
- One concern per commit.
