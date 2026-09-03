# Elimelec cutover plan — Teese → Odoo 19

Version 1, 03/09/2026. Prepared by Elite Advisors for Elimelec SARL (Douala).
Currency XAF, dates DD/MM/YYYY. The published, formatted edition of this
document is the "Elimelec Cutover Plan" artifact; this file is the copy of
record in the repository.

| | |
|---|---|
| Accounting cutoff | **31/08/2026** |
| Teese export synced | 26/08/2026 (5 days short of cutoff) |
| Odoo work starts | 01/09/2026 |
| Trial balance upload | target 20/09/2026 |
| Production | https://nekoutb-odoo-elite-ad.odoo.com — `elite_clearance` 19.0.9.0.0 |

## 1 · Principles

1. **One cutoff, one trial balance.** The legacy books close on 31/08/2026.
   Every balance enters Odoo through one opening entry as of that date,
   prepared by the accountant. Nothing migrated before that entry may post.
2. **History is record-keeping.** Dossiers, advances and invoices from Teese
   are imported so a file shows what was spent and billed, with the billing
   reference the client knows, but carry no journal entry. Legacy invoices
   are draft customer invoices that a server-side guard refuses to post.
3. **Every imported row keeps its Teese identifier** — the import is
   idempotent and can be rehearsed on staging any number of times.
4. **Client data never enters the repository** (it is public).
5. **Rehearse on staging, then production.**
6. **Work from 01/09/2026 is keyed in Odoo** through the live workflow, not
   migrated. Teese has been unreachable since ~29/08/2026.

## 2 · Sources

| Source | State | Yields | Owner |
|---|---|---|---|
| Teese warehouse export (zip, 6 tables) | in hand | 190 clients, 3,644 dossiers, 7,272 advances, 1,258 invoices / 6,308 lines, 10,713 validations; synced 26/08 | Elite Advisors |
| Teese `bi` schema (28 tables, live server) | server down since ~29/08 | masters (employees 32, departments 11, ports, types, *rubriques* 7, tills 4, banks 4, users 37), dossier step history (12,375), cash movements (6,207), purchases (45/49), payments (near-empty) | TS Consulting |
| Accountant's trial balance at 31/08/2026 + sub-ledgers | to produce | every opening balance; detail for 411 per open invoice, 401 per supplier, 421 per employee, 5xx per bank/till, 44x VAT, fixed assets, equity | Accountant |
| Bank / mobile-money statements at 31/08 | to collect | confirms each 5xx balance; till counts | Elimelec finance |
| HR files (contracts, payslips, CNPS numbers, dependants) | to collect | employee master, contracts, payroll inputs | Elimelec HR / DG |
| Old Odoo Online db | lapsing | partner CSV only | Elite Advisors |

**Decision needed:** ask TS Consulting for a dump of the raw schema or at
least the `bi` tables as of 31/08/2026. Without it the step history, the
*rubriques*, the tills and the 27–31/08 window are lost to Odoo. The trial
balance still covers the money; only records would be missing.

## 3 · Phases

| # | Phase | Status 03/09 | Owner | Effort |
|---|---|---|---|---|
| 0 | Platform and module: Odoo.sh prod/staging, CI (51 tests), `elite_clearance` 19.0.9, `elite_clearance_teese` 19.0.3 | done | Elite Advisors | — |
| 1 | Chart of accounts and journals: install `l10n_cm` (SYSCOHADA) **first**; add 47xx débours engagés, 421101 personnel débours avancés (auxiliary = employee contact), fee income; journals Sales, 4 tills, 4 banks, Mobile Money, Maviance, Misc, **Opening**; Settings → Clearance | next | Accountant + Elite Advisors | ½ day |
| 2 | Masters: clients/suppliers (importer) then enrich from `dim_client`/`dim_fournisseur`; employees 32 + departments 11; ports; service types (AUTRE stays *Autre*); map 7 *rubriques* onto the 21 seeded categories; users = only staff who transact (Enterprise seats), never the 37 Teese logins | partly done | Elite Advisors, HR | 1 day |
| 3 | Operational history: run the importer on staging, reconcile to the appendix, then production; decide the bulk-close date for old "open" dossiers | built | Elite Advisors, Ops checks | 1 day |
| 4 | Opening balances at 31/08/2026: one Opening-journal entry, sub-ledgers as detail lines (411 per open invoice with billing ref, 401 per supplier, 421101 per person, 5xx per journal); controls | to do | Accountant prepares, EA loads | 2 days |
| 5 | Catch-up 01/09 → go-live through the live workflow; payments on legacy invoices go against the opening 411 line, never the imported draft; 27–31/08 invoices re-keyed from paper (second small zip) or listed for 411 detail | running | Elimelec ops/finance | continuous |
| 6 | HR and payroll (parallel track, see §6) | to do | HR, EA, accountant | 3 weeks |
| 7 | Sign-off; uninstall importer; retire Teese | to do | DG, accountant, EA | ½ day |

## 4 · Financial records

Teese exposed no general ledger, chart of accounts, bank/cash ledgers or VAT
declarations. The financial migration is **balance-based**: the accountant's
TB at cutoff is the source of truth; Teese transactions are imported as
records, not accounting.

### The opening entry

| Account | Detail level | Source | Control |
|---|---|---|---|
| 411 Clients | one line per open invoice: partner, `ref` = billing reference, due date | customer ledger at 31/08, cross-checked to imported drafts' *Outstanding at Export* (26/08) adjusted for 27–31/08 payments | Σ = TB 411; client statements agree |
| 401 Fournisseurs | per supplier (per bill if available) | supplier ledger | Σ = TB 401 |
| 421101 Personnel — débours avancés | per staff member (partner = employee work contact) | advance register; the 7,199 Teese "unjustified" flags are a lead, not a balance | Σ = TB 421101 |
| 47xx Débours engagés | total or per file | TB | = disbursed not yet recharged |
| 52x/57x banks and tills | per journal | statements, till counts | each = statement |
| 443x/445x TVA | collected / deductible | TB, August return | agrees to the return |
| 2xx/28x fixed assets | gross and depreciation per asset, then the Assets app | register | NBV agrees |
| 1xx equity, 12x result | totals | TB | entry balances to zero |

Per-invoice 411 lines matter: a client paying `EL26IM228` in October is
reconciled against a receivable carrying that reference; the imported draft
cannot be posted, so the opening line is where the reference lives.

### Advances and 421101

Teese disbursed 2,600,928,938 XAF over 7,272 lines (positive rows
2,652,615,630). Only 73 carry Teese's "justified" flag — plainly not
maintained — so it is kept verbatim and not acted on. What staff actually
owe at cutoff is the accountant's 421 register, loaded per person. From
01/09 the module's flow applies: an advance names a registered employee,
sits on 421101 against them, and only a documented justification
reclassifies it to 47xx and makes it billable.

### Not migrated as accounting

Cash movements (opening till balances only; archive the table if delivered),
client payments (effectively absent; *montant encaissé* is the collection
figure), purchase requests/orders (re-key open ones if Purchase is adopted).

## 5 · Operational records

| Teese object | Odoo destination | Status |
|---|---|---|
| Dossier (3,644) | `logistics.file` — code as reference, client, type, port, follow-up employee, dates, cargo, regime, incoterm, importer; 8 duplicate codes renamed, 7 undated dated from code, sequences advanced | importer |
| Avance de frais (7,272) | `logistics.expense`, `is_legacy`, settled-direct, unposted, category Legacy; excluded from every total and gate | importer |
| Facture (1,258) + lignes (6,308) | `account.move` **draft**, `is_legacy`, cannot be posted; Teese HT/TTC/outstanding kept; one "TVA (as invoiced in Teese)" line so the draft totals the Teese TTC; shown under the file's Billing, greyed; 44 without file | importer |
| Étapes de dossier (12,375) | new model `logistics.file.step` + stage templates per service type — lead-time reporting | needs the `bi` dump |
| Validations (10,713) | archived CSV on the import record | importer |
| Documents attached in Teese | attachments on file/expense | unknown — ask TS Consulting |

## 6 · HR and payroll

**Applications:** Employees (already a dependency), Contracts, Payroll
(Enterprise `hr_payroll` + `hr_payroll_account`), Time Off (Cameroon leave and
holidays), Attendances optional. The Expenses app is *not* used for
disbursements — the clearance advance flow replaces it.

**Employee master:** from `dim_employe` (32) and `dim_departement` (11):
matricule → Identification No., profession → job title, hierarchy →
departments, en_service → active. Add CNPS number, birth date, marital
status, dependent children, bank account, risk group. The work contact
(auxiliary on 421101) is created automatically.

**Odoo 19 ships no Cameroon payroll localization** (the documented list has
no CEMAC/OHADA member). The structure is built as salary rules in a third
module, `elite_hr_payroll_cm`, with tests against known payslips.
Third-party "paie Cameroun" modules exist for 16/17; none verified on 19.

### Salary rules (CGI 2025, CNPS schedule — accountant to confirm)

| Rule | Base | Rate | Side | SYSCOHADA |
|---|---|---|---|---|
| Gross (basic + allowances + benefits in kind at art. 33 rates) | contract | — | — | 661/663 |
| CNPS pension, employee | gross ≤ 750,000/month | 4.2 % | deduction | 4311 |
| Professional expenses | gross | 30 %, cap 400,000 | IRPP base only | — |
| IRPP base | gross − expenses − CNPS employee (+ BIK) | annualised − 500,000 (art. 29) | — | — |
| IRPP (art. 69) | annual base | 10 % ≤ 2 M · 15 % to 3 M · 25 % to 5 M · 35 % above | deduction /12 | 4471 |
| CAC | IRPP | 10 % | deduction | 4471 |
| RAV / CRTV | salary band | 13,000 at the example salary | deduction | 4472 |
| TDL | salary band | 2,500 at the example salary | deduction | 4473 |
| CFC employee / employer | gross | 1 % / 1.5 % | both | 4474 |
| CNPS pension, employer | gross ≤ 750,000 | 4.2 % | employer | 664/4311 |
| CNPS family allowances | gross ≤ 750,000 | 7 % general (5.65 % agri, 3.7 % private education) | employer | 664/4311 |
| CNPS work accidents | gross, no cap | 1.75 % A · 2.5 % B · 5 % C | employer | 664/4311 |
| FNE | gross | 1 % | employer | 664/4475 |
| Recovery of unjustified advance | employee's 421101 balance | agreed instalment | deduction | 421101 |
| Net to pay | — | — | — | 422 → 52x |

The last rule closes the loop with the clearance module: a waived advance
still sits on 421101 against the holder; payroll deduction, with written
agreement and within the legal ceiling, is how it is recovered.

### Worked example (acceptance case)

Gross 300,000, general regime, risk A, two children, no BIK:

```
CNPS employee 4.2 %                          12,600
IRPP base  300,000 − 90,000 − 12,600 = 197,400 → annual 2,368,800 − 500,000 = 1,868,800 → 10 %
IRPP 186,880 / 12                            15,573
CAC 10 % / 12                                 1,558
RAV 13,000 · TDL 2,500
NET TO PAY                                  254,769
Employer: PF 7 % 21,000 · pension 12,600 · AT 1.75 % 5,250 · FNE 3,000 = 41,850
TOTAL COST                                  341,850
Family allowances (CNPS, info) 2 × 4,500      9,000
```

CFC omitted until Elimelec's rates are confirmed; the rule exists, switched off.

**Accounting and declarations:** one Payroll journal; batch posts 661, 664,
4311, 447x, 422, 421101. Monthly CNPS return and DIPE; annual DIPE, CNPS
statement, tax certificates.

**Rollout:** collect HR files → load employees/departments → contracts →
build and test the structure (the example is the first test) → one-month
parallel run → first live batch → post → declarations from Odoo figures.

## 7 · Timeline

| When | What | Elimelec | Accountant | Elite Advisors | TS Consulting |
|---|---|---|---|---|---|
| w/c 07/09 | Phase 1 on production; request `bi` dump; HR files | DG, HR | confirms accounts | installs, configures | delivers dump |
| w/c 07/09 | Phase 3 rehearsal on staging; reconcile; pick old-dossier close date | Ops checks samples | — | runs | — |
| w/c 14/09 | Phase 3 on production; Phase 2 enrichment; users and groups | names users | — | runs | — |
| by 20/09 | Phase 4: TB at 31/08 with detail; opening entry loaded and controlled | statements, till counts | **prepares TB** | loads, controls | — |
| w/c 21/09 | Phase 5 complete; September closed in Odoo | keys backlog | reviews | supports | — |
| 21/09 → 09/10 | Phase 6: HR, contracts, payroll structure, parallel run | HR data | validates | builds, tests | — |
| by 09/10 | Phase 7 sign-off; Teese retired; importer uninstalled | DG signs | signs | executes | closes access |

**Go-live checklist:** Odoo TB at 31/08 = accountant's, line by line; 411/401/
421101 detail sums to control accounts, three client statements checked;
legacy import reconciled to the appendix, 0 `account.move` posted by it, 0
rows after cutoff or each explained; every September transaction keyed and
the September VAT return produced from Odoo; six team users tested as
themselves; backups verified; zip archived on the import record.

## 8 · Risks and open decisions

| Item | Impact | Mitigation / decider |
|---|---|---|
| No `bi` dump | step history, *rubriques*, tills, 27–31/08 records lost | TB covers money; re-key from paper; TS Consulting chased by DG |
| 411 detail delivered as a total | manual client statements forever | insist on per-invoice detail; drafts' outstanding figures are the checklist |
| 2,285 dossiers typed AUTRE | weak reporting | re-type from `dim_type_dossier` or accept; Ops |
| 3,642 dossiers "open" since 2011 | noise in lists and gates | bulk-close before a chosen date; Ops picks the date |
| "RANDY" as supplier on 129 advances | misfiled staff advances | Elimelec confirms; re-attribute |
| No Cameroon payroll localization | custom structure; yearly Finance Law changes | tests; accountant confirms rates each year |
| RAV/TDL bands, CFC rates | wrong deductions | accountant supplies scales before the parallel run |
| Enterprise seats | cost per user | only transacting staff get logins |
| Public repository | data exposure if ever committed | rule in place; consider private |

## Appendix

### A.1 Figures the import must reproduce

| Figure | Teese export | Where in Odoo |
|---|---|---|
| Clients | 190 | Contacts, Legacy ID set |
| Files | 3,644 + 1 | Clearance Files, filter Legacy (Teese) |
| Files closed | 2 | state Complete |
| Expenses | 7,272 | Expenses, filter Legacy (Teese) |
| — reversals / parked | 299 / 554 | `legacy_reversal` / `LEGACY-UNALLOCATED` |
| Advances total, positive rows | 2,652,615,630 | sum of non-cancelled legacy expenses |
| Invoices (credit notes / without file) | 1,258 (3 / 44) | Invoicing, filter Imported (Teese), all Draft |
| Invoice lines | 6,308 (+ Teese-VAT lines) | |
| Billing total TTC | 3,426,779,457 | list Total footer |
| Outstanding at export (26/08) | 2,975,319,557 | *Outstanding at Export* — informational |
| Posted by the import | 0 | Confirm refused on any imported invoice |
| Rows after 31/08/2026 | 0 expected | `count_after_cutoff` |

### A.2 Running the importer

Newest staging build → Connect → Apps → Update Apps List → Clearance Files at
19.0.9.0.0 (upgrade if lower) → install *Clearance Files — Teese Legacy
Import* → Settings → Clearance accounts and sales journal → Clearance →
Configuration → Teese Legacy Import → New → upload zip → Import (reopen and
press again if the browser times out; it resumes) → compare with A.1.
Judgement calls: `docs/legacy-migration-teese.md`.
