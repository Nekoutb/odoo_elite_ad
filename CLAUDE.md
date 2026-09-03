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
  <in the Odoo.sh project settings — never in this repository, it is public>, Custom plan). The old Odoo Online db (elite-advisors,
  saas~19.3) holds no data and will lapse. Never build against 19.3 minor APIs.

## The module: addons/elite_clearance (v19.0.8.0.0)
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
  approved → settlement_approved → settled [→ justified, advances only].
- **Segregation of duties (owner spec, 03/09/2026).** Groups are TEAMS:
  Operations / Customer Service / Transit (each with a Manager), Finance,
  Finance Manager, plus the older general Manager (config, doc waivers,
  reopen). An expense is KEYED only by an originating team, never Finance
  (`_check_originating_team`, su-exempt so hooks/tests pass; admin is NOT
  exempt). It is APPROVED by any team manager. The settlement fields
  (`payment_mode`, `journal_id`, `vendor_id`, `employee_id` —
  `SETTLEMENT_FIELDS`) are Finance-only on create AND write; an originator
  submits without them. Finance fills them on an `approved` expense, the
  Finance Manager signs (`action_approve_settlement` → `settlement_approved`),
  and only then can Finance settle. `payment_mode` has no default any more.
- **Ops-close gate.** `action_close_operations` requires the caller to pass
  the `ops_close` approval (Operations Manager) AND `customs_fee_amount`
  non-zero — the fee is keyed by hand from the declaration and a file closed
  without it would bill without it.
  Postings: direct settle Dr 47xx Débours engagés / Cr journal (cash|bank|
  Mobile Money|Maviance); advance settle Dr 421101 Personnel débours avancés
  / Cr journal; justify (requires ≥1 attachment) Dr 47xx / Cr 421101.
  Accounts configured per company in Settings → Clearance (res.company
  fields clearance_*_account_id, clearance_misc_journal_id,
  clearance_sale_journal_id).
- **Staff advances (owner spec, 03/09/2026).** An advance MUST name a
  registered `hr.employee` — enforced from keying, not from submission.
  421101 is ONE account with the staff member's `work_contact_id` as the
  auxiliary (partner-as-auxiliary, Odoo's native subsidiary ledger); there
  are deliberately no per-employee accounts in the chart. Per-staff balances
  come from the Partner Ledger. `hr.employee.create` is overridden to make
  that contact, because hr only creates it as a side effect of writing a
  work e-mail or phone. Justification is the reclassification 421101 → 47xx
  and is the ONLY thing that makes a disbursement billable.
- **The unjustified-advance gate.** `unjustified_advance_total` (settled
  advances not yet justified) blocks ops-close and billing. A new
  `group_clearance_ops_manager` — deliberately NOT the Manager who approved
  the expense nor the Finance user who paid it — may waive it with a written
  explanation (`advance_waiver_*` fields). The waiver releases the FILE, never
  the money: the unjustified amount is never recharged, stays on 421101
  against the holder, and remains recoverable from them.
- Approval checkpoints route through `res.company._clearance_check_approver`
  and the `APPROVAL_KINDS` table in `models/res_company.py`: an explicit
  user list per company wins; empty falls back to the security groups (a
  tuple — `expense` accepts any of the three team-manager groups).
- Billing (ops_closed only): action_create_invoice builds out_invoice —
  recharge lines at cost against the OOP balance-sheet account (clears it,
  taxes explicitly cleared) + fee lines to fee income, which DO keep default
  taxes: commission = service_type.commission_rate% × OOP total PLUS manual
  `customs_fee_amount` (two lines — Reading A, confirmed by owner
  behaviourally, not explicitly). Mark Complete requires posted invoice.
  Reopen only via wizard: Manager + written reason. Cancel past draft needs
  the waiver approver, refuses once the invoice is posted, and refuses while
  any expense is still live.
- **Legacy data (Elimelec's Teese, 03/09/2026).** Second module
  `addons/elite_clearance_teese` = one-off importer of the six-table
  warehouse zip (uploaded on `logistics.legacy.import`, NEVER committed —
  the repo is public). Idempotent on `legacy_id`. Durable fields it needs
  are in elite_clearance: `logistics.port`, cargo/routing on the file,
  `employee_id` (follow-up, hr.employee), `invoice_ids` via
  `account.move.logistics_file_id`, `is_legacy` on expenses. Legacy
  expenses are settled-direct, unposted, and excluded from `oop_total`, the
  advance gate and new invoices (`is_legacy` in every compute).
  **Record-keeping only (owner, 03/09/2026): no trial-balance impact.**
  Cutoff 31/08/2026, TB uploaded as of that date. Legacy invoices are
  `logistics.legacy.invoice` (read-only, one state `imported`, shown greyed
  on the file under "Imported Billing (Teese)") — NEVER account.move. The
  importer records `export_synced_at` (26/08 for the first export: 5 days
  short of cutoff) and counts rows after cutoff. Context
  `skip_checklist` / `legacy_import` bypass checklist generation and the
  file-in-progress check. Judgement calls in
  `docs/legacy-migration-teese.md` — read it before touching TYPE_MAP.
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
- **`target="inline"` no longer exists** on `ir.actions.act_window`: 19.0
  offers only current / new / fullscreen / main, and an invalid value is a
  hard install failure, not a warning. A `res.config.settings` action sets no
  target at all and adds `'bin_size': False` to its context — copy
  `base_setup.action_general_configuration`, not a pre-19 module.
- **One compute method may not feed both a stored and a non-stored field.**
  Stored computes default to `compute_sudo=True`, non-stored to `False`; the
  registry warns twice on every load. Split the method.
- **`ir.sequence.date_range.create()` ignores `number_next`.** With the
  standard implementation it seeds the PostgreSQL sequence from
  `number_next_actual`, which `default_get` pins to 1. Create the range
  bare, then `write({'number_next': N})` — only write() issues
  `ALTER SEQUENCE ... RESTART WITH`. Cost one CI cycle on 03/09/2026.
- Static checks (compile, XML well-formedness) cannot see an invalid *value*
  in a valid tag. Only installing the module catches that — which is what CI
  is for, and why it must stay green rather than merely exist.
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
- Tests (throwaway db, currently 50 tests across both modules, must stay green):
  `docker compose run --rm odoo odoo -d clr_test -i elite_clearance,elite_clearance_teese --with-demo --test-enable --test-tags /elite_clearance,/elite_clearance_teese --stop-after-init`
- Static repo checks CI also runs: `python tools/check_manifest.py addons/elite_clearance addons/elite_clearance_teese`

## Roadmap / backlog (owner-approved)
1. Odoo.sh: project exists, production branch is `prod` (Odoo.sh pins the
   production branch name; it could not be changed to `19.0` — see
   `docs/deployment-odoo-sh.md`). `19.0` is a retired duplicate to delete
   from the console. Load `l10n_cm` before the module.
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
4b. Recovering a waived advance from the holder (payroll deduction, or a
   write-off through the parked `logistics.oop.adjustment`) is NOT built —
   today the residue simply sits on 421101 for the accountant to clear.
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
- **Never delete a branch on GitHub that Odoo.sh has in a stage.** Odoo.sh
  binds the stage to the branch NAME; deleting it strands the stage and
  blocks the console until the branch is restored. Change the stage in the
  console first, then delete. `prod` taught us this on 03/09/2026 — and
  the same day taught that the production branch cannot be swapped from
  the console at all (one per project, drag = merge, delete refused).
- Push to `staging` only. Promoting is `git push origin staging:prod`, a
  separate, explicit step on the owner's word.
- `.gitignore` and `.gitattributes` exist for a reason: never commit
  `__pycache__`, and everything is stored LF because the deploy target is
  Linux.
