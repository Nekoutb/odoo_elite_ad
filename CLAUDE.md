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

## The module: addons/elite_clearance (v19.0.16.0.0)
Customs clearance job files for a logistics/clearance services provider.
- `logistics.file` — one file = one clearance job. States:
  draft → in_progress → ops_closed → done (+cancel, +imported). `imported`
  = brought over from Teese as a record: no work, no new expense, no
  billing, no cancelling. Billing one is an exception — the Billing Agent
  (`group_clearance_billing`) requests reopening with a reason, an Operations Manager approves
  (`reopen_request_*`, approval kind `reopen_imported`) → in_progress.
  Owner spec 03/09/2026. Gate: cannot start work
  with mandatory documents missing unless an approver signs a waiver
  (reason logged to chatter). Each file auto-creates an analytic account
  (plan "Clearance Files"); EVERY posting carries it.
- Document checklist generated from `logistics.service.type` templates.
  Receiving stamps ONE shared transaction timestamp (env.cr.now()) for all
  lines saved together; bulk override via the Set Received Date/Time wizard.
- `logistics.expense` — out-of-pocket expenses. draft → submitted →
  approved → settlement_submitted → settlement_approved → settled
  [→ justified, advances only]. Finance keys mode / journal /
  holder-for-an-advance on an `approved` expense, confirms or corrects
  the vendor the originator named (`action_submit_settlement` still
  refuses a cash/electronic expense with no vendor) and SENDS it; the
  Finance Manager approves or returns
  (`action_return_settlement`); the money then leaves through the
  **Cashier** for a cash journal or **Treasury** for bank/mobile money
  (`_check_disburser` routes on `journal_id.type`; kinds `cash_disburse` /
  `bank_disburse`). Both groups imply Finance. **Administrators
  (`base.group_system`) are exempt from the "Finance never keys" creator
  gate** — admin is seeded into every group, so it fired on the owner in
  the lab; administrators configure, they do not operate.
- **Segregation of duties (owner spec, 03/09/2026).** Groups are TEAMS:
  Operations / Customer Service / Transit (each with a Manager), Finance,
  Finance Manager, plus the older general Manager (config, doc waivers,
  reopen). An expense is KEYED only by an originating team, never Finance
  (`_check_originating_team`, su-exempt so hooks/tests pass; admin is NOT
  exempt). It is APPROVED by any team manager. The settlement fields
  (`payment_mode`, `journal_id`, `employee_id` — `SETTLEMENT_FIELDS`) are
  Finance-only on create AND write; an originator submits without them.
  Finance fills them on an `approved` expense, the Finance Manager signs
  (`action_approve_settlement` → `settlement_approved`), and only then can
  Finance settle. `payment_mode` has no default any more. **`vendor_id` is
  NOT a settlement field (owner 06/09/2026):** WHO is paid is the spending
  team's knowledge, keyed in the capture dialog; only HOW is Finance's.
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
  DRAFT `account.move` with `is_legacy=True` (owner's choice, 03/09/2026,
  over a separate read-only model); `account.move.action_post` REFUSES
  is_legacy, so "not posted" is enforced, not hoped. The draft totals
  exactly the Teese TTC via one "TVA (as invoiced in Teese)" line. The file
  never sets `invoice_id` to an imported draft, and `action_create_invoice`
  ignores legacy invoices in its already-has-invoice check. The importer
  records `export_synced_at` (26/08 for the first export: 5 days short of
  cutoff) and counts rows after cutoff. Context
  `skip_checklist` / `legacy_import` bypass checklist generation and the
  file-in-progress check. Judgement calls in
  `docs/legacy-migration-teese.md` — read it before touching TYPE_MAP.
- **Analytic tags read `2026AI0072 - CTC` (owner spec, 03/09/2026).** The
   analytic account's `name` IS the label: file number once, hyphen, then the
   client's three-letter `res.partner.clearance_slug`. `code` still holds the
   bare number for search. `account.analytic.account._compute_display_name`
   is overridden FOR THE CLEARANCE PLAN ONLY to use `name` verbatim, because
   Odoo's own version renders `[code] name - full client name` — which showed
   the number twice and made every tag a different width. The slug is
   generated by `res.partner._clearance_ensure_slug()` at the client's first
   file and never regenerated: initials when the name has 3+ telling words
   (noise words like SARL/DU/DES are dropped), otherwise the opening letters;
   collisions break on the third character. It is UNIQUE across partners and
   only a Clearance Manager can correct it — correcting it does NOT rename
   analytic accounts already created, since those names sit on posted lines.
- **Owner spec 03/09/2026, second pass.** `payment_mode` is now
   cash / electronic / advance (no more `direct`; a pre- migration splits it
   by journal type and empties it on legacy rows). A vendor and an advance
   holder are mutually EXCLUSIVE, greyed in the form and enforced by
   `_check_one_counterparty`. Paying a vendor routes through that vendor's
   own `property_account_payable_id` (401100): the settlement move is four
   lines — Dr 47xx / Cr 401100(vendor), Dr 401100(vendor) / Cr journal — so
   the supplier ledger works and the cash still leaves the same day.
   Justifying an advance now needs the Operations Manager:
   `action_submit_justification` (Finance, needs an attachment) →
   `justification_submitted` → `action_justify` (kind `justification`).
   Billing may recharge at other than cost via `recharge_amount`.
   **WRITING that field IS the request** (`_sync_recharge_state` in
   `write()`) — the first version used a button and the owner adjusted
   50,000 to 45,000 with nothing happening. Any existing approval is torn
   up when the figure changes. Above cost needs `recharge_ops`; BELOW cost
   needs `recharge_ops` AND `recharge_gm` (the GENERAL Manager, owner's
   revision 03/09/2026 — it was the Finance Manager) plus a written reason
   AND an attachment on the file. The disbursement lines always recharge at
   COST so 47xx clears in full; the difference lands in its own P&L account
   — `clearance_oop_undercharge_account_id` (expense, negative line) or
   `clearance_oop_overcharge_account_id` (income), configured in Settings
   and refused at billing if unset. Commission and customs fee now credit separate
   706 subdivisions (`clearance_commission_account_id`,
   `clearance_service_fee_account_id`), each falling back to the old single
   fee account. Files sort newest-first with a Created On column.
- **The expense timeline (owner spec, 03/09/2026).** One readonly stamp per
   step, written by the action that performs it: `date_requested` (default
   today, at keying), `date_submitted`, `date_approved`,
   `date_settlement_submitted`, `date_settlement_approved`, `date_settled`
   ("Paid On"), `date_justified`. `date_documents_submitted` is stamped by
   an `ir.attachment.create` override — the upload dates its own arrival,
   first document only. Shown in a Timeline group on the form.
- **Never open logistics.expense in an o2m dialog.** Its form has nine
   conditionally-visible header buttons, a statusbar and a chatter; saving
   that inside a dialog crashed Owl (`VToggler.remove`, "Illegal
   invocation") and left a phantom row in the file's list. The file's
   expense list therefore opens a CAPTURE form in its dialog
   (`logistics_expense_view_capture_form`, `form_view_ref` in the o2m
   context) — no header, no statusbar, no chatter, and only the fields an
   originator keys; the settlement fields are Finance's and are absent.
   The row carries a Submit button and an Open button, so the workflow is
   one click away on the record's own page. Owner spec 06/09/2026: the
   inline editable row is gone.
   **The dialog (owner 06/09/2026, second pass):** category, description,
   amount, vendor, requested-on, and a Documents field — no unit (it is
   "Par dossier" for every disbursement; the field keeps its default and
   still prints). `attachment_ids` is a COMPUTED many2many over the
   attachments pointing at the expense, inversed by pointing new ones at
   it and deleting removed ones, so the dialog, the chatter and the
   justification count see ONE set. The widget
   `clearance_expense_documents` (`static/src/expense_documents/`) is
   `many2many_binary` plus `useDropzone` over the enclosing
   `.modal .o_form_view`: a file dropped anywhere on the dialog is posted
   to `/web/binary/upload_attachment` exactly as the Upload button posts
   it (`model`, `id` 0 for a new record, `csrf_token`, `ufile`) and
   linked. Business fields go readonly past `submitted`, as on the page.
- **The billing screen (owner spec, 03/09/2026).** `ops_closed` now reads
   "OK for Billing". The **Billing** button opens `logistics.billing.wizard`:
   a disbursement section (one row per `_billable_expenses()`, columns
   Disbursed / To Recharge / Variance) and a service section pre-filled with
   "Commission sur débours" and "Honoraires Agréés en Douane", to which the
   biller may add rows. Any variance makes `needs_review` true and the only
   button becomes **Submit for Review**, which writes
   `logistics.file.recharge_amount` and so trips the existing Ops (+ GM
   below cost) approval. Per-line intent is persisted on
   `logistics.expense.recharge_amount`. `action_create_invoice` and the
   wizard share `_create_client_invoice(debours, services)`; the debours
   lines always post AT COST so 47xx clears, and the variance is one further
   line to the under/overcharge account.
   **Split bill (owner 07/09/2026).** `split_invoices` on the wizard
   issues TWO invoices from the same lines: `clearance_invoice_kind`
   `'debours'` (the disbursements at cost + the variance line, no VAT at
   all) and `'services'` (commission, HAD, extra services, with VAT);
   an unsplit bill is `'full'`. `logistics.file.invoice_id` is then the
   SERVICES invoice and `debours_invoice_id` the other, so everything
   that asks "is the file billed?" keeps reading `invoice_id`;
   `_client_invoices()` returns the live one or two (disbursements
   first) for completion, cancel, balance due and Preview. The printed
   document drops the VAT row on a `'debours'` invoice and prints only
   its own side's advance rows (`account.move._clearance_advances()`:
   HAD/DAU + VAT on it → services, "autres avances" → disbursements —
   the attribution is the module's reading, flagged to the owner). A
   split needs lines on both sides or it is refused.
   **A split pair is ONE bill.** `bill_stands` / `invoices_posted`
   (compute_sudo, on the file) are the single answer to "billed?" and
   "posted?" for the buttons, the actions and the My Tasks SQL: a
   cancelled half means not billed and not posted, so Mark Complete
   refuses and the file is back in the queue. `_standing_half()` finds
   the live half; the wizard then forces `split_invoices`, shows which
   half is issued again (`reissue_kind`) and `_create_client_invoice`
   issues ONLY that half, leaving the standing one (posted, perhaps)
   untouched. The choice itself is `billing_split` on the file, written
   by `_persist()` and restored by `default_get`, so it survives a
   recharge review. Preview prints the pair with a `page-break-before`
   between documents (the legacy CSS property — wkhtmltopdf's WebKit
   does not know `break-before`); `test_clearance_invoice_print.test_32`
   counts the pages through the real wkhtmltopdf.
   Both pointers are `ondelete='restrict'` and `account.move` has an
   `@api.ondelete` saying why: every gate reads them, so a DELETED half
   would leave the survivor reading as the whole bill (found by review,
   07/09/2026). While a half stands, its side is frozen —
   `_check_standing_half()` refuses to issue the other half against
   figures the standing one does not carry (a debours invoice has no
   tax, so its untaxed total IS the recharge it was issued at), and
   `_persist()` writes back only the side being issued.
   **Four gates, ONE group (06/09/2026):** the Billing / Resume Billing /
   Request Reopening / Mark Complete buttons, `APPROVAL_KINDS['billing']`,
   the wizard's ACL rows and `clearance.task.KIND_GROUPS['billing']` all
   name `group_clearance_billing`. When the department was created the
   buttons were left on Finance: Billing saw no button, Finance saw one
   that was refused, and the owner reported the dialog gone. The group
   implies `account.group_account_invoice` (the invoice is an
   `account.move`) and `base.group_partner_manager` (internal users can
   only READ `res.partner`, and the screen writes the client's details).
   `test_billing_wizard.test_20/21` open the file form with `get_view()`
   as a Billing-only and a Finance-only user and assert on the arch —
   Odoo strips `groups=`-gated nodes server-side, so that is the one
   ORM-level test that sees what the browser shows.
- **My Tasks (owner spec, 03/09/2026).** `views/clearance_tasks_views.xml`:
   ten group-restricted actions under a "My Tasks" menu, so each role sees
   only the queue it can act on. No new model — domains over the existing
   states.
- **Analytic on EVERYTHING (owner spec, 03/09/2026).** Every line of every
  move carrying `logistics_file_id` gets the file's analytic account —
  income, expense, asset, liability, the receivable and the tax lines Odoo
  computes itself. Done by `account.move._clearance_stamp_analytic()`,
  called from `create()` and from `_post()` (the second pass catches the
  payment-term and tax lines Odoo adds late). Existing distributions are
  never overwritten. CONSEQUENCE, deliberate: the analytic balance per file
  nets to ZERO — it is a per-file journal, not a per-file P&L. Margin comes
  from the file's own totals or an analytic report filtered by account type.
  The expense settle/justify moves now set `logistics_file_id`, and the
  advance settlement no longer withholds the tag.
- References are structured, not from a static ir.sequence: files
  `2026IM0009`, invoices `EL26IM0001`, one ir.sequence per
  (kind, service type, company) created on first use by
  `logistics.file._next_reference`. Only `logistics.expense` uses a plain
  declared sequence.

## Hard-won Odoo 19 gotchas (do not relearn these)
- `<group expand="0">` invalid in search views. Kanban template is
  `<t t-name="card">`. `t-esc`→`t-out`. `_sql_constraints` is IGNORED —
  use `models.Constraint` class attributes (name starts with `_`).
  `groups_id`→`group_ids` — including the field that restricts an
  `ir.ui.view` to groups, which cost a CI cycle on 03/09/2026 despite
  being written down right here; `tools/check_view_pitfalls.py` now
  fails the static job on it. Demo data needs `--with-demo` (default
  flipped).
- **readonly fields in one2many lists are DROPPED on save for new rows**
  unless `force_save="1"` — this caused our worst bug. Always browser-test
  the real save path; unit tests run as admin and miss access errors.
  **It also bites rows keyed in a DIALOG**: when the dialog closes,
  `StaticList.validateExtendedRecord()` calls `_restoreActiveFields()`
  and the row is serialised with the LIST's modifiers, not the form's.
  The file's expense list had `readonly="1"` on category/description
  (pointless on a non-editable list) and the browser test's row arrived
  with both NULL (07/09/2026). Never put readonly on a column of a
  non-editable x2many list; it does nothing visible and eats the value.
- **NEVER render a PDF inside a TransactionCase.**
  `_render_qweb_pdf(..., force_report_rendering=True)` runs wkhtmltopdf,
  which fetches the asset bundles back off the live HTTP server while the
  test's transaction still holds its locks: both CI jobs hung for an hour
  with no output and no failure (07/09/2026). Assert on the HTML from
  `_render_qweb_html` instead - a page break is a CSS rule, and the rule
  is in the HTML. The browser test is the place where a real render is
  exercised, and it goes through Chrome, not wkhtmltopdf.
- **There IS a browser test now.** `tests/test_expense_dialog_tour.py`
  (`HttpCase`) drives `static/tests/tours/expense_dialog_tour.js` in a
  headless Chrome; CI installs Google's `google-chrome-stable` deb +
  `python3-websocket` in both Odoo jobs (the odoo:19 image is Ubuntu
  noble, where apt's `chromium` is a snap stub with no browser in it) and
  FAILS a run in which the test was skipped, because Odoo only logs a
  skip when Chrome is missing. Tour files live in
  `web.assets_tests` (loaded only with `--test-enable`, never on
  staging). Odoo 19 tour rules learnt writing it: a step's `run` function
  is called with `this.anchor` = the trigger element; while a modal is
  open every trigger must sit INSIDE it unless it starts with `body`;
  triggers are hoot selectors (`:contains`, `:visible`, `:has`,
  `:not`); `queryFirst` takes the first match. The drag is simulated with
  one `DataTransfer` shared by the `dragenter` and `drop` events.
- **The file form must open for an agent with NO accounting rights.**
  Ops / Customer Service / Transit agents are not in any `account.*`
  group. A compute on `logistics.file` that reads `invoice_id` /
  `invoice_ids` as that user raises AccessError, and an embedded
  `invoice_ids` list makes `web_read` fail outright - the first browser
  test (07/09/2026) found the file form would not open for the people
  who work it. Rule: every figure read off the invoices is
  `compute_sudo=True`; the invoice list and Preview button carry
  `groups="account.group_account_invoice,account.group_account_readonly"`;
  `test_segregation.test_02b` opens the form with `Form(file.with_user(u))`
  for each role - that is `web_read` with the view's own spec, the
  browser's path.
- **An onchange that clears a field which turns readonly in the same
  breath needs `force_save="1"`** on that field, or the cleared value is
  never sent (readonly values are dropped on save - same trap as the
  one2many one). The expense's vendor/holder pair does exactly this.
- **A related `readonly=False` field is inversed ONE AT A TIME.** Each
  becomes its own `write()` on the target, so a constraint on the target
  that wants several fields together refuses the first write for the
  ones not yet written. Use plain wizard fields and write them back in
  one `write()` (the billing screen's shipment box does).
- **Manifest data order is load order.** `%(action_x)d` in a view resolves at
  load time, so the file defining `action_x` must be listed first. The wizard
  view files therefore precede `views/logistics_file_views.xml`, and
  `views/clearance_menus.xml` is last.
- **`target="inline"` no longer exists** on `ir.actions.act_window`: 19.0
  offers only current / new / fullscreen / main, and an invalid value is a
  hard install failure, not a warning. A `res.config.settings` action sets no
  target at all and adds `'bin_size': False` to its context — copy
  `base_setup.action_general_configuration`, not a pre-19 module.
- **`_get_name_invoice_report()` is a GUARD in Odoo 19, not a dispatch.**
  `account.report_invoice` renders `account.report_invoice_document` only
  `t-if` the method returns that exact name, so overriding it to return your
  own template makes Send & Print produce a BLANK page. You must ALSO inherit
  `account.report_invoice` and add your own `t-if`/`t-call` branch. Odoo names
  the record `o`; a template that only knows `doc` dies on its path. Cost a
  live report outage 06/09/2026.
- **`primary` on a `<template>` may only ever be `"True"`.** `import_xml.rng`
  declares a single permitted value, so `primary="False"` fails the whole
  module install with "Element odoo has extra content: template" — naming the
  FIRST template in the file, not the offending one. An extension template
  omits the attribute. Guarded by `tools/check_view_pitfalls.py`.
- **Teese holds NO contact detail for customers.** `wh_dim_partner.csv` is
  `id,tenant_id,odoo_id,name,ref,is_company,write_date` — a name and a ref,
  nothing else, for all 190. So the invoice's client block (address, e-mail,
  NIU, RC) cannot come from the migration and must be entered. Those four are
  therefore demanded at BILLING, not at file creation (owner 06/09/2026):
  gating file creation on them would stop Operations opening a file for any
  imported client. The billing screen offers the four fields as `related=…
  readonly=False`, so the agent fixes the CUSTOMER record while billing.
  The three SHIPMENT essentials (BL, goods, RVC) are offered on the same
  screen for files opened before they became mandatory — as PLAIN wizard
  fields written back in `_persist()`, NOT related ones: Odoo inverses
  related fields one at a time, and the file's constraint wants all three
  at once, so the first write-through would be refused for the two not yet
  written. The file form's `required=` on those fields applies in
  draft/in_progress only: the web client SAVES before it calls a button,
  and a required-but-blank field on an older ops_closed file stopped the
  Billing button from ever firing.
  Clearance → Configuration → Customers opens on the incomplete ones for
  export/import in bulk.
- **Odoo never passes `--encoding` to wkhtmltopdf.** It relies on the
  `<meta charset>` in `web.minimal_layout`, which sits AFTER two inlined
  asset bundles — far past the window a parser reads a charset hint in — so
  wkhtmltopdf falls back to Latin-1 and every accent in the PDF becomes
  mojibake (`N°`→`NÂ°`, `Catégorie`→`CatÃ©gorie`, nbsp→`Â`). The source
  files are fine; only the PDF is wrong. `models/ir_actions_report.py`
  appends `--encoding utf-8`. Cost a live report 06/09/2026.
- **CI installs; production UPGRADES. They are different code paths.** A
  `translate=True` Char is stored as jsonb, and REMOVING `translate=True`
  does not convert an existing column - Odoo leaves it. A fresh install had
  a varchar column and passed; staging, upgraded from the previous build,
  kept jsonb and `clearance.task` died with "UNION types character varying
  and jsonb cannot be matched" for every user. Two guards now: the
  `Upgrade from what production runs` CI job installs prod's version and
  upgrades to HEAD before running the suite, and `clearance.task._text()`
  reads a name column whichever type it is. Cost a live staging outage
  04/09/2026.
- **An `_auto = False` model over other tables must flush them itself.** The
  ORM flushes pending writes only for the models a query names; a
  `_table_query` view names none of them, so a record written a moment ago
  is missing from the results and it looks like an access-rights problem.
  Call `self.env['x'].flush_model()` for every source table at the top of
  `_search`. `clearance.task` does; cost one CI cycle 04/09/2026.
- **`<group string="...">` is invalid inside a search view** (valid in a
  form). The group-by block must be a bare `<group>`; anything else is
  refused when the view loads. Guarded by `tools/check_view_pitfalls.py`.
- **A stored computed field may NOT be `required=True`.** `create()` inserts
  the row and computes stored computes on the following flush, so the NOT
  NULL is checked before the compute has run and every create fails on
  INSERT. Enforce it with an `@api.constrains` instead.
- **Two stacked `@api.depends` on one method: only the OUTER one counts.**
  Each decorator overwrites the function's `_depends`; the inner list is
  silently dead. `_compute_invoice_balance_due` carried a stray
  `@api.depends('documents_complete', 'waiver_state')` above its own for
  weeks (it belonged to `_compute_can_start` below) — one list per method.
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
- **An inherited view may NOT set groups on the record.** Odoo 19: "Inherited
  view cannot have 'groups' defined on the record. Use 'groups' attributes
  inside the view definition." Put `groups="..."` on the element inside the
  arch. Guarded by `tools/check_view_pitfalls.py`.
- **Never declare one xml id twice**, especially not once outside and once
  inside a `<data noupdate="1">` block: the second declaration flips
  `ir.model.data.noupdate`, which silently freezes the first one on every
  later upgrade.
- The app icon is generated, not hand-drawn: `tools/render_clearance_icon.py`
  writes `static/description/icon.png` (100x100, transparent, no tile) and
  the matching `icon.svg`. Design A, "Stamp on a file", approved by the owner
  03/09/2026. Odoo 19 core icons have NO tile and put a darker third tone
  where two shapes overlap — re-cut with the script, never by hand.
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
- Tests (throwaway db, currently 77 tests across both modules, must stay green):
  `docker compose run --rm odoo odoo -d clr_test -i elite_clearance,elite_clearance_teese --with-demo --test-enable --test-tags /elite_clearance,/elite_clearance_teese --stop-after-init`
- Static repo checks CI also runs:
  `python tools/check_manifest.py addons/elite_clearance addons/elite_clearance_teese`
  `python tools/check_view_pitfalls.py addons/elite_clearance addons/elite_clearance_teese`

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
