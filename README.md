# Elite Advisors — Clearance Files (Odoo 19)

Odoo 19 module that runs a customs clearance and logistics services business
as job files: one file per clearance instruction, with a documentation gate,
out-of-pocket disbursements, employee cash advances, and client recharge
billing that clears the balance sheet.

| | |
|---|---|
| Module | `addons/elite_clearance` |
| Version | `19.0.46.0.0` (staging) · `19.0.44.0.0` (production) |
| Odoo | 19.0 Community (lab) / 19.0 Enterprise (production, Odoo.sh) |
| Licence | LGPL-3 |
| Currency / locale | XAF, Cameroon (SYSCOHADA — `l10n_cm`) |

---

## What it does

**Everything reaches the analytic account.** Every line of every journal
entry and invoice the module produces carries the file's analytic account —
income, expense, asset and liability alike, including the receivable and the
tax lines Odoo computes for itself. The analytic account is therefore a
complete per-file journal; because both sides of every move are tagged, its
*balance* nets to zero by design, and per-file margin comes from the file's
own totals or from an analytic report filtered by account type.

**`logistics.file` — the clearance job file.**
`draft → in_progress → ops_closed → done`, plus `cancel`. Every file creates
its own analytic account under the *Clearance Files* plan at creation, and
every posting the module makes carries that account. Per-file profitability
therefore falls out of the accounting rather than out of a spreadsheet.

**The documentation gate.** Each `logistics.service.type` carries a checklist
template. Opening a file generates the checklist. Only Customer Service opens
a file, and work starts when the **Head of Customer Service approves the
opening**; with a mandatory document missing the file asks for a **waiver**
instead, which the same head signs with a written reason posted to the
chatter — the approval itself starts the work. Ticking documents stamps one
shared transaction timestamp (`env.cr.now()`) across everything saved
together; the *Set Received Date/Time* wizard back-dates in bulk.

**File numbers.** References are structured per service type (`2026IM0009`).
Under *Clearance → Configuration → Settings → File Numbering* each service
takes the last number the old system issued; the next file opened continues
from it (`2026IM0019` keyed, `2026IM0020` issued). A malformed reference, or
one behind a file already opened here, is refused.

**`logistics.expense` — out-of-pocket disbursements.**
`draft → submitted → approved → settlement_submitted → settlement_approved
→ settled`, and for advances a further `justified` step that requires at
least one attachment.
Each step is a different pair of hands:

| Step | Who |
|---|---|
| Key and submit | Operations, Customer Service or Transit team — **never Finance**. The free text is *Additional Comments* |
| Approve | The **Head of the service that keyed it** |
| Name who is paid (the vendor) | The team that keyed it, when keying; Finance may correct it at settlement |
| Set how it is paid (cash / electronic / advance, holder for an advance, journal) and send it on | Finance — the originator cannot even see these fields |
| Sign the settlement, or return it to Finance | Finance **Manager** |
| Disburse cash / pay from the bank | **Cashier** (tills) / **Treasury** (bank, mobile money) |
| Submit an advance's justification | The staff member holding it, or Finance — never asked for a non-justifiable category |
| Approve the justification | Head of Service **Operations**, then the Head of Service **Finance** signs the entry |
| Raise the invoice | **Billing Agent** |
| Recharge above cost | Operations **Manager** |
| Recharge **below** cost | Head of Service **Operations** and the **General Manager**; every adjusted line carries its own written reason (or the biller gives one overall note) |
| Review a recharge | The approver is taken straight to the **billing screen** — disbursed, recharged, variance and the reason side by side — and approves or refuses there |
| Refuse anything | The approver gives a **reason in a dialog**; it is posted on the record and the person who asked is notified |
| Everything | The **Clearance Administrator** passes every checkpoint, named approver lists included |
| Close the file for operations | Operations **Manager**, and only once the customs fee is keyed |
| Reopen an imported file | **Billing Agent** requests with a reason; Operations **Manager** approves after review |

| Step | Debit | Credit |
|---|---|---|
| Settle, paid direct from a till | 47xx Débours engagés (via 401 for a vendor) | Cash journal |
| Settle, paid through a bank, Mobile Money or Maviance | 47xx Débours engagés (via 401 for a vendor) | **That bank's own holding account** (its *Outstanding Payments* account) |
| Bank statement line matched | Bank holding account | 52xx Bank |
| Settle, via advance | 421101 Personnel débours avancés | Till, or the bank's holding account |
| Justify an advance | 47xx Débours engagés | 421101 Personnel débours avancés |

Each bank-type journal needs its own reconcilable *Outstanding Payments*
account (*Accounting → Configuration → Journals → Outgoing Payments*), or a
payment through it is refused at the *Disburse / Pay* button. The bank
account then moves once per payment, when the statement is matched, and the
holding account's balance is what has been paid but is not yet through the
bank.

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

**Opening a file.** Everything under Cargo & Routing is keyed when the file
is opened (the Responsible user names who follows it; there is no separate
follow-up employee field), and a draft stays its author's own until the
opening is approved — Finance, Transit and Operations see it from that
moment, not before. Cargo that is not in a container is marked **Not Containerised**, and
the container count and type are then switched off. Supporting documents are
dragged straight onto the Document Checklist.

**Billing.** From `ops_closed`, `action_create_invoice` raises a customer
invoice with two sections: disbursements recharged at cost against the
out-of-pocket account (clearing it, and carrying no tax — they are the
client's own liability paid on their behalf), then the fee lines, which do
carry VAT: the commission (`service_type.commission_rate` % of the
out-of-pocket total, printed as "Commission sur débours" with no percentage
on the client's document) and the manually keyed customs service fee, as two
separate lines. The VAT is the one named under *Clearance → Settings → VAT on
Service Fees*, or else the Accounting *Default Sales Tax*; a customer ticked
**Exempt from VAT** is billed without it; with neither configured for a
non-exempt customer, billing is refused rather than issued without VAT. The billing screen can **split the bill**: one invoice for the
disbursements alone (they carry no VAT), another for the commission and fees
(with VAT), each printed as the same document. Invoice references are
structured per service type (`EL26IM0001`); file references likewise
(`2026IM0009`).

A file cannot be marked complete until that invoice is posted — both invoices
of a split bill; if one half is cancelled, the billing screen issues that half
again and the other stands. Reopening a
closed file goes through a wizard that demands a manager and a written reason.

**Approvals.** Every checkpoint — documentation waiver, expense approval,
settlement approval, disbursement, billing, operations close, unjustified-
advance waiver — takes an explicit list of users under *Settings → Clearance*.
Where no list is configured the security groups above apply; the Clearance
Administrator passes either way.

**My Tasks and the bell.** Every checkpoint is a row in *My Tasks*, narrowed
to what the reader can act on, and lands with a toast and a beep; the bell
lists the newest task first. A recharge awaiting approval opens on the
billing screen, not on the file.

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
docker compose run --rm odoo odoo -d clr_test -i elite_clearance,elite_clearance_teese --with-demo --test-enable --test-tags /elite_clearance,/elite_clearance_teese --stop-after-init
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
