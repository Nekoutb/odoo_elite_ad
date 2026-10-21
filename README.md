# Elite Advisors — Clearance Files (Odoo 19)

Odoo 19 module that runs a customs clearance and logistics services business
as job files: one file per clearance instruction, with a documentation gate,
out-of-pocket disbursements, employee cash advances, and client recharge
billing that clears the balance sheet.

| | |
|---|---|
| Module | `addons/elite_clearance` |
| Version | `19.0.47.0.0` (staging) · `19.0.44.0.0` (production) |
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
bank. Every journal item of a disbursement is labelled *category / file
number*; the entry's reference names the disbursement.

**Cash from the till.** *Disburse / Pay* on a cash journal needs no other
evidence: it prints the **cash voucher** (*Avance frais* — letterhead from
the company record, requester, till, date of the request, file and client,
category, amount, and every approval with its name and time stamp) and keeps
it on the disbursement. The Cashier has it signed by the person taking the
cash and uploads the signed copy; the file cannot be closed for operations
until every cash payment has one. The *Payment Channel* field lists every
till and bank of the company, the same list for everybody.

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
follow-up employee field). From the moment it is saved, every clearance
team — Customer Service, Operations, Transit, their heads and Finance — sees
it under *Files*. Cargo that is not in a container is marked **Not Containerised**, and
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
billing screen, not on the file. *My Tasks* also has an **Ongoing files**
section: every file in progress on which the reader has keyed a cost.

**Recharge review, line by line.** Any disbursement charged at other than
what it cost sends the bill for review — even when an overcharge on one line
and an undercharge on another add up to cost. Operations approves; the
General Manager too where any line or the total is below cost. Changing the
lines after approval lapses it; a refusal bills at cost.

## Legacy data (Elimelec / Teese)

`addons/elite_clearance_teese` is a one-off importer for the Teese warehouse
export: upload the zip on *Clearance → Configuration → Teese Legacy Import*.
It is record-keeping only — legacy invoices arrive as **draft** customer
invoices and nothing is posted;
the balances arrive as a trial balance at the 31/08/2026 cutoff. It is idempotent and never puts
the data in this repository. The mapping,
every judgement call and the reconciliation figures are in
[docs/legacy-migration-teese.md](docs/legacy-migration-teese.md). Uninstall
it after go-live; the fields it needs live in `elite_clearance`.

### Legacy uploads (19.0.55, brief of 19/10/2026)

The zip importer is superseded by the owner's own load scripts, which
feed the module through the API. *Clearance → Legacy uploads* groups
what they need:

- **Two loads.** The Sage general ledger to 31/08/2026 is loaded as plain
  journal entries (not through the module). The Teese history to
  16/10/2026 is loaded with `model.load()` on files, checklist lines,
  disbursements, invoices and invoice lines under the context key
  `clearance_migration=True`, each row carrying an external id so a
  second load updates instead of duplicating; then
  `logistics.file.action_migration_finalize()` posts the invoices, marks
  the billed files as billed, frozen and locked, and books the débours
  result when due. Both calls are idempotent.
- **Every Teese invoice is posted**, whatever its date; its lines land
  on the accounts named in Settings according to their clearance
  category (débours, service, VAT), never on an account given by the
  load. A disbursement paid on or before 31/08/2026 is loaded with
  `accounting = record_only` and posts nothing; one paid after, or
  unpaid, posts through the legacy channel mapped under *Payment
  Channels*.
- **Files opened on or before the cutoff** (`clearance.legacy_cutoff_date`,
  16/10/2026) may be saved, started and billed with mandatory fields
  missing; a banner lists them. Their disbursements go through the single
  legacy débours account 471100 with the customer as partner. A file
  opened after the cutoff is checked like a new one and keeps the
  two-account scheme.
- **A billed file is locked**: the file, its disbursements and its
  invoice lines are read-only, in Python, for the screens, Odoo's Import
  and the API alike. *Re-open for Additional Billing* is the Head of
  Customer Service's, takes a reason, keeps the earlier round frozen and
  opens the next one; re-billing invoices only the new round and posts
  only the change in the débours result.
- **The débours result** of a fully paid legacy file (billed débours,
  Handling excluded, less débours incurred) is booked once on 758801 or
  658801 when the file is billed and every approved disbursement is
  paid; until then it reads Pending. A daily job and a button on the
  file re-evaluate it.
- **The accountant's two actions** on an approved disbursement nobody
  paid here: *Confirm Sage Payment* (settled, record only, nothing
  posted) and *Cancel Approval* (reason required). The list *Approved
  Expenses Awaiting Payment* shows them, older than 60 days in red.

### Handling due to the customer (19.0.56, brief of 20/10/2026)

Some files are billed with a **Handling** component. It is printed on
the invoice, but it is not revenue, carries no VAT and is never
incurred: it is due back to the customer and reduces what they owe.

- **The component.** A billable service or an expense category ticked
  *Handling – due to customer*. The billable service *HAND — Handling
  (dû au client)* is seeded and approved; the biller picks it in the
  service section of the billing screen. No disbursement can be keyed
  under a Handling category. The invoice line carries the flag from the
  moment it is billed; a migrated line brings it from the load file;
  the description is never read.
- **The entry.** The invoice debits the customer's receivable for its
  full total, Handling included. Each Handling line is credited to the
  *Handling Account* named in Settings - empty, which is the default,
  means the customer's own receivable account - with the customer as
  partner and the ledger label `<file> | <invoice> | Handling – dû au
  client`. When that account is the receivable, the credit is matched
  against the invoice's debit inside the entry: the open balance of the
  invoice is its total less the Handling, the invoice still reads *Not
  Paid*, and the customer statement shows both. A customer who pays the
  gross amount is left with the excess as a credit, to refund or offset.
- **Controls.** A Handling line posted anywhere else, carrying VAT, or
  naming another partner is refused at posting. A credit note on a
  Handling line reverses the credit, matched the same way, so the open
  balance does not move. Handling is outside the débours result on both
  sides.
- **Reporting.** *Reporting → Handling Due to Customers* lists every
  Handling line of a posted invoice or credit note by customer, file,
  document and month, with filters on whether the invoice is still
  open. The file's Débours Result group and list carry a *Handling*
  figure.

**The customer record** (21/10/2026): an incomplete record never stops
a file from opening or being worked; the banner on the file says what
the invoice will need, and the invoice is refused until Customer
Service completes it. The refusal, on the file and on the billing
screen, carries a button straight to the customer record. The e-mail
address is shown but never demanded.

**Disbursement references** read `FA` + year + month + the running
number of the year (FA26051022) since the same build. *Settings → File
Numbering* takes the last reference the old system issued and the next
disbursement keyed here takes the number after it, with its own month.

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
