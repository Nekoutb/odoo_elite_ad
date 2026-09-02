# CLAUDE.md — Elite Advisors Clearance Module (Odoo 19)

Standing context for working in this folder. Read before any task.
User-facing documentation lives in `README.md` and `docs/`; this file is the
working memory that is *not* obvious from the code.

## Who and what
- Owner: NEKOUT BOMA, Elite Advisors (Douala, Cameroon). Financial advisory +
  AI/process automation. Formal tone; never invent facts; verify everything;
  currency XAF; dates DD/MM/YYYY. English for technical material.
- This folder is a local Odoo 19 **Community** lab (docker compose:
  odoo:19 + postgres:16, port 8069). `addons/elite_clearance` is the ONLY
  deliverable — everything else here is disposable scaffolding.
- Production target: fresh Odoo.sh project on 19.0 (Enterprise subscription
  M260529302698425, Custom plan). The old Odoo Online db (elite-advisors,
  saas~19.3) holds no data and will lapse. Never build against 19.3 minor APIs.

## The module: addons/elite_clearance (v19.0.4.0.0)
Customs clearance job files for a logistics/clearance services provider.
- `logistics.file` — one file = one clearance job. States:
  draft → in_progress → ops_closed → done (+cancel). Gate: cannot start work
  with mandatory documents missing unless an approver signs a waiver
  (reason logged to chatter). Each file auto-creates an analytic account
  (plan "Clearance Files"); EVERY posting carries it.
- Document checklist generated from `logistics.service.type` templates.
  Receiving stamps ONE shared transaction timestamp (env.cr.now()) for all
  lines saved together; bulk override via the Set Received Date/Time wizard.
- `logistics.expense` — out-of-pocket expenses. draft → submitted →
  approved → settled [→ justified, advances only].
  Postings: direct settle Dr OOP / Cr journal (cash|bank|Mobile Money|
  Maviance journals); advance settle Dr Employee Advances / Cr journal
  (partner = employee.work_contact_id); justify (requires ≥1 attachment)
  Dr OOP / Cr Advances. Accounts configured per company in Settings →
  Clearance (res.company fields clearance_*_account_id,
  clearance_misc_journal_id, clearance_sale_journal_id).
- Approval checkpoints route through `res.company._clearance_check_approver`
  and the `APPROVAL_KINDS` table in `models/res_company.py`: an explicit
  user list per company wins; empty falls back to the security group.
- Billing (ops_closed only): action_create_invoice builds out_invoice —
  recharge lines at cost against the OOP balance-sheet account (clears it,
  taxes explicitly cleared) + fee lines to fee income, which DO keep default
  taxes: commission = service_type.commission_rate% × OOP total PLUS manual
  `customs_fee_amount` (two lines — Reading A, confirmed by owner
  behaviourally, not explicitly). Mark Complete requires posted invoice.
  Reopen only via wizard: Manager + written reason. Cancel past draft needs
  the waiver approver, refuses once the invoice is posted, and refuses while
  any expense is still live.
- References are structured, not from a static ir.sequence: files
  `2026IM0009`, invoices `EL26IM0001`, one ir.sequence per
  (kind, service type, company) created on first use by
  `logistics.file._next_reference`. Only `logistics.expense` uses a plain
  declared sequence.

## Hard-won Odoo 19 gotchas (do not relearn these)
- `<group expand="0">` invalid in search views. Kanban template is
  `<t t-name="card">`. `t-esc`→`t-out`. `_sql_constraints` is IGNORED —
  use `models.Constraint` class attributes (name starts with `_`).
  `groups_id`→`group_ids`. Demo data needs `--with-demo` (default flipped).
- **readonly fields in one2many lists are DROPPED on save for new rows**
  unless `force_save="1"` — this caused our worst bug. Always browser-test
  the real save path; unit tests run as admin and miss access errors.
- **Manifest data order is load order.** `%(action_x)d` in a view resolves at
  load time, so the file defining `action_x` must be listed first. The wizard
  view files therefore precede `views/logistics_file_views.xml`, and
  `views/clearance_menus.xml` is last.
- **Never declare one xml id twice**, especially not once outside and once
  inside a `<data noupdate="1">` block: the second declaration flips
  `ir.model.data.noupdate`, which silently freezes the first one on every
  later upgrade.
- The post-install hook matches master data on `code`. Demo records therefore
  use `DEMO-` prefixed codes; an unprefixed demo `BL` would be adopted as the
  real one and the proper French label would never be created.
- `sudo()` scoped to single calls (e.g. analytic account creation);
  restricted-user tests exist for a reason — keep adding them.
- Community = "Invoicing" menu, no TB/P&L reports (Enterprise/OCA territory).
  Lab db chart may be Generic; production must load l10n_cm (SYSCOHADA) FIRST.

## Commands
- Start: `docker compose up -d`   Stop: `docker compose down`
- Apply code changes: `docker compose restart odoo` then Apps → module → Upgrade
  (XML/schema need the Upgrade; Python needs the restart).
- Logs: `docker compose logs odoo`
- Tests (throwaway db, currently 25 tests, must stay green):
  `docker compose run --rm odoo odoo -d clr_test -i elite_clearance --with-demo --test-enable --test-tags /elite_clearance --stop-after-init`
- Static repo checks CI also runs: `python tools/check_manifest.py addons/elite_clearance`

## Roadmap / backlog (owner-approved)
1. Odoo.sh deploy: create `19.0` (production) / `staging` / `dev/*` branches
   and point the project at them — see `docs/deployment-odoo-sh.md`. Load
   `l10n_cm` before the module.
2. OOP adjustment (parked, spec agreed): `logistics.oop.adjustment` —
   non-recharged residue written off to P&L expense, over-recovery to income;
   closed reason-code list (client refused / error / duplicate / FX /
   commercial gesture / other); approval; file cannot fully close with
   non-zero unadjusted OOP balance; keeps the file's analytic tag.
3. Fee question to re-confirm with owner: commission + manual customs fee
   are TWO lines (Reading A) — implemented; owner has not explicitly signed off.
   Second open question: fee lines keep default taxes while recharge lines do
   not. Believed correct (TVA on services, débours out of scope) — confirm.
4. Lock received timestamps option — owner undecided.
5. Multi-level disbursement thresholds if needed.
6. French (`fr_CM`) translation: no `i18n/` yet, module ships English source
   strings with French domain terms in the seeded master data.
7. Later: CSV import of partners from old Online db; OCA
   account_financial_report if TB/P&L wanted in lab.

## Rules for changes
- Never edit Odoo core. Bump manifest version on schema change. Migration
  scripts under migrations/<version>/ (pre-/post-/end-). One thing per
  commit; run the test suite before calling anything done; test as a
  restricted user (Clearance/User only) before delivering.
- `.gitignore` and `.gitattributes` exist for a reason: never commit
  `__pycache__`, and everything is stored LF because the deploy target is
  Linux.
