# Legacy migration — Teese (Elimelec) → Clearance Files

Elimelec's legacy system is **Teese** (TS Consulting). What we have of it is
the BMS *warehouse* export: six denormalised CSV tables in one zip, synced
on 26/08/2026. The live Teese server has been unreachable since ~29/08/2026,
and the 28-table `bi` star schema it exposed was never dumped — only these
six tables exist.

The import is the module **`elite_clearance_teese`**. It is a one-off tool:
install it on the target database, upload the zip on *Clearance →
Configuration → Teese Legacy Import*, press *Import*, read the log.
Uninstall it after go-live; the fields it relies on live in
`elite_clearance` and stay.

**The data never enters this repository** — it is public. The zip is uploaded
on the import record and stored as an attachment in the database only.

## The principle: record-keeping only, no trial-balance impact

The legacy books close on the **cutoff date, 31/08/2026**, and their account
balances are uploaded to Odoo as a trial balance as of that date. Nothing
the import creates may therefore touch the ledger:

- legacy expenses carry no journal entry (`is_legacy`, excluded from every
  billing total);
- legacy invoices are **draft customer invoices** (`account.move`, state
  *Draft*), flagged `is_legacy`, and **`action_post` refuses them**: a
  server-side guard, not a convention. They appear in Invoicing and on their
  file with the billing reference the client knows, and can never count
  revenue or a receivable twice against the uploaded balances.

The import records when the export was synchronised from Teese and warns
if that predates the cutoff. **This export was synced on 26/08/2026 — five
days short.** Anything Teese recorded from 27/08 to 31/08 is not in it, and
with the Teese server down since ~29/08 it may not be recoverable. The
trial balance covers the money; the missing days would only be missing
*records* (dossiers, advances, invoices dated in that window).

## What is in the export

| Table | Rows | Becomes |
|---|---|---|
| `wh_dim_partner` | 190 | `res.partner` (customers) |
| `wh_fact_dossier` | 3,644 | `logistics.file` |
| `wh_fact_advance` | 7,272 | `logistics.expense`, flagged legacy |
| `wh_fact_invoice` | 1,258 | `account.move` — **draft**, `is_legacy`, cannot be posted |
| `wh_fact_invoice_line` | 6,308 | `account.move.line` (tax-free, plus one Teese-VAT line per invoice) |
| `wh_fact_validation` | 10,713 | archived as an attachment; not data |

Not in the export, so not migrated: employees and departments as masters
(only names on dossiers), ports and dossier types as masters (only names),
expense categories (*rubriques*), cash tills, bank accounts, users, the
dossier **step history** (`fait_etape_dossier`, 12,375 rows), cash
movements, purchases, and any general ledger. If the live server ever
answers again, those are the tables to ask TS Consulting for.

## Fields added to `elite_clearance` (v19.0.9.0.0)

| Model | Field | From |
|---|---|---|
| `logistics.file` | `port_id` → new `logistics.port` | `port_name` |
| | `employee_id` (follow-up employee, `hr.employee`) | `employee_name` |
| | `shipment_type` container / conventional / flatbed | `embarquement` |
| | `container_count`, `package_count`, `weight_kg`, `cargo_value` | as named |
| | `customs_regime` (Char) | `regime` (EX1, EX2) |
| | `incoterm_id` → `account.incoterms` | `incoterm` (CIF, CFR, FCA, CPT) |
| | `importer_name` | `importer` |
| | `invoice_ids` (several invoices per file) via `account.move.logistics_file_id` | one dossier carries up to 8 invoices |
| | `legacy_id`, `legacy_type_name` | provenance |
| | `legacy_invoice_count`, `legacy_billed_total`, `legacy_outstanding_total`, `legacy_expense_total` | the Billing block: revenue and disbursements side by side |
| `logistics.expense` | `date_requested` | `requested_date` |
| | `is_legacy`, `legacy_id`, `legacy_justified`, `legacy_reversal` | provenance |
| `account.move` | `logistics_file_id`; `is_legacy`, `legacy_id`, `legacy_amount_untaxed`, `legacy_amount_total`, `legacy_amount_residual`, `legacy_payment_state`; `action_post` refuses `is_legacy` | `wh_fact_invoice` |
| `res.partner` | `legacy_id` | |

`legacy_id` is what makes every re-run idempotent: rows already present are
skipped and counted.

## The judgement calls, and why

**Dossier type → service type by label, not by code prefix.** The code
(`2026IM0531`) is already in this module's reference format, but the export
shows the same prefix under several types (`IM` under both AUTRE and MISE A
LA CONSOMMATION). The label is the only reliable signal:

| Teese `type_name` | Service type |
|---|---|
| MISE A LA CONSOMMATION | `IM` Import |
| EXPORT STANDARD | `ES` Export Standard |
| ENLEVEMENT DIRECT ET APUREMENT | `ED` (created) |
| AUTRE (2,285 dossiers) | `AU` Autre (created) |

The raw label is kept on the file as `legacy_type_name` so the mapping can be
revisited. The code itself is imported verbatim as the file reference.

**Eight duplicate codes.** The first occurrence keeps the code; the second is
imported as `<code>-<legacy id>` and logged. Nothing is dropped.

**Seven dossiers without an opening date** get 1 January of the year in
their code, and a log line.

**Sequences are advanced.** New files created for a (year, code) the legacy
data already used start after the highest imported number — otherwise the
first new 2026 import file would be `2026IM0001`, which exists. Only our own
codes can collide; legacy prefixes we don't use (`EX`, `ET`, `TP`…) are left
alone.

**Advances: settled-direct, legacy, outside every total.** The export carries
no payment mode, no holder, no till or bank, no category. All 7,272 were
disbursed. Only 73 are flagged justified in Teese — 1%, which says the flag
was not maintained rather than that 99% of history is unsupported. They are
imported as settled, paid direct, category *Legacy — non catégorisé*, with
the Teese flag kept verbatim in `legacy_justified`. **No journal entry is
posted for them** — the general ledger comes from the accountant's trial
balance, not from this export — and `is_legacy` keeps them out of
`oop_total`, the unjustified-advance gate and any new invoice. They are
history, visible, filterable, and inert.

**299 reversals** (289 negative, 10 zero) are kept with their absolute
value, cancelled, flagged `legacy_reversal`, so the audit trail is complete
and no total counts them.

**554 advances with no dossier** land on one parking file,
`LEGACY-UNALLOCATED`, to be reallocated by hand.

**Suppliers** arrive as free-text names (281). Matched case-insensitively on
partner name, created as suppliers otherwise. *RANDY* (129 lines) looks like
a staff member, not a supplier — a business question, not one the import
can answer.

**Invoices as drafts that cannot be posted.** Each of the 1,258 legacy
invoices becomes a **draft customer invoice** carrying its Teese **billing
reference** (`EL26IM228`), date, client, and every line as exported, tax-free,
each labelled with its legacy product:

| Legacy product | Label on the line | Pass-through |
|---|---|---|
| 1447 | Débours | yes — out-of-pocket account |
| 1449 | Honoraires | no — fee income account |
| 5538 | Débours douane — vacation / liquidation | yes |
| 5541 | Droits de douane | yes |

Teese's own VAT is not reproducible from a rate — it is 4.7% of the fee base
overall, so exemptions were applied per line — so one extra line, *TVA (as
invoiced in Teese)*, carries the difference between the Teese total and the
sum of the lines. The draft therefore totals **exactly what the client was
invoiced**. The Teese figures themselves (fee base, total, outstanding at
export, payment state) are kept on the move as `legacy_*` fields.

`is_legacy` does three things: `account.move.action_post` **refuses** it; it
is greyed out with an *Imported* ribbon and an explanatory banner; and the
file workflow ignores it — `invoice_id` (the invoice *Mark Complete* waits
on) is never set to an imported draft, and *Create Invoice* on a still-open
legacy file raises a real invoice beside the imported ones.

Opening a file shows every invoice — imported and issued in Odoo — in the
**Billing** block, with *Imported Billing (Teese TTC)* and *Outstanding at
Export* totals, and directly above it the expenses with an *Imported
Disbursements (Teese)* total, so revenue and out-of-pocket read together.
In Invoicing, the *Imported (Teese)* / *Issued in Odoo* filters separate
them; the 44 invoices Teese never tied to a dossier are there with no file.

**Validations** (approval circuits, 10,713 steps) are history about a
workflow that is being rebuilt as Odoo approvals. Archived as a CSV
attachment on the import record.

## Reconciliation — what to compare after the run

| Figure | Teese export | Where in Odoo |
|---|---|---|
| Partners | 190 | Contacts, filter *Legacy ID set* |
| Files | 3,644 (+1 `LEGACY-UNALLOCATED`) | Clearance Files, filter *Legacy (Teese)* |
| Files closed | 2 | state Complete |
| Expenses | 7,272 | Expenses, filter *Legacy (Teese)* |
| of which cancelled reversals | 299 | `legacy_reversal` |
| of which parked | 554 | on `LEGACY-UNALLOCATED` |
| Advances total, positive rows | 2,652,615,630 XAF | sum of legacy expenses not cancelled |
| Imported invoices | 1,258 (3 credit notes, 44 without a file) | Invoicing → Customers → Invoices, filter *Imported (Teese)* — all **Draft** |
| Imported invoice lines | 6,308 (+ one Teese-VAT line where VAT ≠ 0) | |
| Imported billing total (TTC) | 3,426,779,457 XAF | that list's *Total* footer |
| Outstanding at export | 2,975,319,557 XAF | sum of *Outstanding at Export* — informational; the receivable is in the trial balance |
| Posted invoices among them | **0**, and *Confirm* is refused | try it on one |
| Rows dated after 31/08/2026 | 0 expected | `count_after_cutoff` on the import record |

## Runbook (staging first)

1. Settings → Clearance: the out-of-pocket and fee-income accounts and the
   sales journal, so the draft lines land on the right accounts. Nothing is
   posted either way.
2. Apps → install *Clearance Files — Teese Legacy Import*.
3. Clearance → Configuration → Teese Legacy Import → New → upload the zip →
   Import. Expect a few minutes. If the request times out, open the record
   again and press Import once more — it resumes, skipping what landed.
4. Read the log on the record. Every renamed duplicate, undated dossier and
   unmatched partner is a line.
5. Compare the counts above.
6. Only then on production. The accountant's task is separate and comes
   after: upload the trial balance as of 31/08/2026.

## Open with Elimelec

- History depth: everything is imported; if 2011–2024 dossiers should be
  archived rather than *in progress*, that is a bulk state change after
  the import, not an import option.
- Who *RANDY* is.
- Whether the 2,285 AUTRE dossiers can be re-typed from another source.
- Whether TS Consulting can still dump the step history and the masters.
