# -*- coding: utf-8 -*-
"""Legacy uploads (owner's change brief v3, 19/10/2026).

The clearance application becomes the single place where files,
disbursements, invoicing and their accounting live, and Teese is the
source of history up to 16/10/2026. Two loads feed it: the Sage general
ledger to 31/08/2026 as plain journal entries (not this module), and
the Teese history through `model.load()` with the context key
`clearance_migration=True`, then `action_migration_finalize()`.

What this file adds, on top of the models it inherits:

* the relief for history - a file opened on or before the cutoff
  (`clearance.legacy_cutoff_date`) may be saved, started and billed
  with mandatory fields missing, and a banner lists them; a file
  opened after it, or re-opened for additional billing, is strict;
* the lock - a billed file, its disbursements and its invoice lines
  are read-only, in Python, so the UI, an import and an XML-RPC call
  are refused alike; re-opening for additional billing is the Head of
  Customer Service's, takes a reason, and starts a new billing ROUND
  in which only new items can be added;
* the accounting of history - a disbursement on a relieved file goes
  through the single legacy débours account (471100, the customer as
  partner) with no accrual; one paid on or before the general-ledger
  cutoff is `record_only` and posts nothing; the Teese invoices are
  POSTED; and the débours result (gain or loss) of a fully paid file
  is booked on its own two accounts, once, and only its change on a
  re-billing;
* the accountant's two actions on an approved disbursement nobody
  paid: confirm the Sage payment, or cancel the approval.

Owner's decisions of 20/10/2026: `is_legacy` keeps its meaning (a
Teese ZIP record, nothing posted) and the relief is `legacy_relief`;
the invoice's own posting IS the entry per invoice; files before
17/10/2026 use the single 471100, later ones the two-account scheme;
re-opening is the Head of Customer Service's.
"""
from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

CUTOFF_PARAM = 'clearance.legacy_cutoff_date'
CUTOFF_DEFAULT = '2026-10-16'
MIGRATION = 'clearance_migration'

# What a disbursement must have reached for the file's débours result to
# count it as incurred, and what counts as paid.
INCURRED_STATES = ('approved', 'settlement_submitted', 'settlement_approved',
                   'settled', 'justification_submitted',
                   'justification_ops_approved', 'justified')
PAID_STATES = ('settled', 'justification_submitted',
               'justification_ops_approved', 'justified')
# The order the replay walks, with the stamp each step writes.
REPLAY_STEPS = [
    ('submitted', 'date_submitted', None),
    ('approved', 'date_approved', 'approved_by_id'),
    ('settlement_submitted', 'date_settlement_submitted', 'settlement_submitted_by_id'),
    ('settlement_approved', 'date_settlement_approved', 'settlement_approved_by_id'),
    ('settled', 'date_settled', 'settled_by_id'),
    ('justification_submitted', 'date_justification_submitted', None),
    ('justification_ops_approved', None, None),
    ('justified', 'date_justified', None),
]
STATE_RANK = {state: i for i, (state, _, _) in enumerate(REPLAY_STEPS, start=1)}
STATE_RANK['draft'] = 0


def _migrating(env):
    return bool(env.context.get(MIGRATION))


# =====================================================================
# The payment channels of the old system, mapped to Odoo's journals
# =====================================================================
class ClearancePaymentChannel(models.Model):
    _name = 'clearance.payment.channel'
    _description = "Legacy Payment Channel"
    _order = 'name'

    name = fields.Char(string="Channel in TEESE", required=True,
                       help="As the old system named it: CAISSE SAGE, "
                            "CAISSE EXCEL, a bank account number...")
    journal_id = fields.Many2one(
        'account.journal', string="Odoo Journal",
        domain="[('type', 'in', ('cash', 'bank'))]",
        help="The till or bank the money left through. A load row naming "
             "a channel with no journal is refused.")
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "Each legacy channel is mapped once per company.")

    @api.model
    def _journal_for(self, name, company):
        """The journal a legacy channel name maps to, or raise."""
        key = (name or "").strip()
        if not key:
            return self.env['account.journal']
        channel = self.search([('name', '=ilike', key),
                               ('company_id', '=', company.id)], limit=1)
        if not channel or not channel.journal_id:
            raise UserError(self.env._(
                "The legacy payment channel '%(name)s' is not mapped to a "
                "journal. Map it under Clearance -> Legacy uploads -> "
                "Payment Channels.", name=key))
        return channel.journal_id


# =====================================================================
# Company settings: the accounts of history
# =====================================================================
class ResCompany(models.Model):
    _inherit = 'res.company'

    clearance_legacy_oop_account_id = fields.Many2one(
        'account.account', string="Legacy Débours Account (471100)",
        help="The single débours account of files opened on or before the "
             "legacy cutoff: every disbursement on them is debited here "
             "with the CUSTOMER as partner, with no accrual through the "
             "supplier, and the invoice credits it. Files opened after "
             "the cutoff use the two-account scheme above.")
    clearance_oop_gain_account_id = fields.Many2one(
        'account.account', string="Gain on Débours (758801)",
        help="Credited with the débours result of a fully paid legacy "
             "file when what was billed exceeds what was incurred.")
    clearance_oop_loss_account_id = fields.Many2one(
        'account.account', string="Loss on Débours (658801)",
        help="Debited with the débours result of a fully paid legacy "
             "file when what was incurred exceeds what was billed.")
    clearance_vat_account_id = fields.Many2one(
        'account.account', string="VAT Collected (443100)",
        help="Where the VAT line of a migrated invoice is credited. The "
             "old system's VAT is not reproducible from a rate, so the "
             "load gives it as its own line and it lands here.")

    @api.model
    def _clearance_legacy_cutoff(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            CUTOFF_PARAM, CUTOFF_DEFAULT)
        try:
            return fields.Date.to_date(raw)
        except (ValueError, TypeError):
            return fields.Date.to_date(CUTOFF_DEFAULT)


# =====================================================================
# The file
# =====================================================================
class LogisticsFile(models.Model):
    _inherit = 'logistics.file'

    # --- provenance and relief -----------------------------------------
    legacy_relief = fields.Boolean(
        string="Opened Before the Cutoff", compute='_compute_legacy_relief',
        store=True, readonly=False, index=True,
        help="Opened on or before the legacy cutoff date, or loaded by the "
             "migration: it may be saved, started and billed with "
             "mandatory fields missing, and the banner lists them. The "
             "relief ends when the file is re-opened for additional "
             "billing.")
    teese_ref = fields.Char(string="TEESE Reference", copy=False, index=True)
    completion_required = fields.Boolean(
        string="Completion Required", copy=False, tracking=True,
        help="Set when a legacy file is re-opened for additional billing: "
             "from then on it is checked like a new file.")
    missing_fields_display = fields.Text(
        string="Missing Mandatory Fields", compute='_compute_missing_fields')

    # --- billing rounds and the lock -------------------------------------
    billing_status = fields.Selection(
        [('not_billed', "Not Billed"), ('billed', "Billed"),
         ('reopened', "Re-opened for Additional Billing")],
        string="Billing Status", default='not_billed', required=True,
        copy=False, tracking=True, index=True)
    # Not stored: it follows bill_stands, which is not stored either. A
    # bill withdrawn by Billing (cancelled, or a half cancelled) unlocks
    # the file for the re-issue the module already allows; only a bill
    # that STANDS locks it.
    is_locked = fields.Boolean(
        string="Locked", compute='_compute_is_locked', compute_sudo=True,
        help="A billed file whose bill stands is read-only except for its "
             "chatter and internal notes, until it is re-opened for "
             "additional billing.")
    billing_round = fields.Integer(
        string="Billing Round", default=0, copy=False, readonly=True,
        help="Incremented at each billing. Items added after a re-opening "
             "belong to the new round.")

    # --- the débours result ----------------------------------------------
    skip_gain_loss = fields.Boolean(
        string="No Débours Result", copy=False, tracking=True,
        help="Set by the migration for files whose result is not booked: "
             "files of 2025, files first billed before 25/02/2026, billed "
             "files with no approved expense in TEESE, documents with no "
             "file. The débours stay in 471100.")
    result_status = fields.Selection(
        [('not_billed', "Not Billed"), ('pending', "Pending Payment"),
         ('due', "Due"), ('posted', "Posted"), ('none', "Not Applicable")],
        string="Débours Result", default='not_billed', required=True,
        copy=False, tracking=True, index=True)
    debours_incurred = fields.Monetary(
        string="Débours Incurred", compute='_compute_debours_result',
        compute_sudo=True, currency_field='currency_id',
        help="Every disbursement approved or later, cancelled ones aside.")
    debours_billed = fields.Monetary(
        string="Débours Billed", compute='_compute_debours_result',
        compute_sudo=True, currency_field='currency_id',
        help="The débours lines of the file's posted invoices, Handling "
             "excluded, net of credit notes.")
    debours_result = fields.Monetary(
        string="Result (billed - incurred)", compute='_compute_debours_result',
        compute_sudo=True, currency_field='currency_id')
    debours_result_posted = fields.Monetary(
        string="Result Already Posted", compute='_compute_debours_result',
        compute_sudo=True, currency_field='currency_id')
    move_ids = fields.One2many(
        'account.move', 'logistics_file_id', string="Journal Entries",
        domain=[('move_type', '=', 'entry')])
    # compute_sudo: an operations agent has no right on account.move,
    # and the file form must open for every role
    entry_count = fields.Integer(compute='_compute_entry_count', compute_sudo=True)

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('date_opened', 'legacy_id', 'teese_ref')
    def _compute_legacy_relief(self):
        cutoff = self.env['res.company']._clearance_legacy_cutoff()
        for file in self:
            file.legacy_relief = bool(
                file.legacy_id or file.teese_ref
                or (file.date_opened and file.date_opened <= cutoff))

    @api.depends('billing_status', 'bill_stands')
    def _compute_is_locked(self):
        for file in self:
            file.is_locked = (file.billing_status == 'billed'
                              and file.bill_stands)

    @api.depends('move_ids')
    def _compute_entry_count(self):
        for file in self:
            file.entry_count = len(file.move_ids)

    # What the module has always demanded server-side, in one list: the
    # regime and the three invoice essentials (also constraints, so a
    # strict file cannot even be saved without them), the cargo figures
    # (demanded at the start of work), and the customer record (demanded
    # at the opening and at billing). The fields the form marks required
    # in draft only (port, incoterm, currency, shipment type, importer)
    # stay the form's business: making them a server gate at close or
    # billing would have blocked every file in progress today.
    MANDATORY_FIELDS = [
        ('customs_regime', "Customs regime"),
        ('bl_awb_ref', "N° BL / N° LTA"),
        ('goods_description', "Produits (the goods being cleared)"),
        ('cargo_value', "Valeur RVC"),
    ]
    CARGO_MANDATORY = [
        ('package_count', "Packages"),
        ('weight_kg', "Weight (kg)"),
    ]

    def _get_missing_mandatory_fields(self, full=True, client=False):
        """The labels of what a new file must carry and this one lacks.
        `full` adds the cargo figures and the customer record: what the
        START of work and the opening demand, and what a re-opened
        legacy file must complete before it is billed again."""
        self.ensure_one()
        missing = [label for name, label in self.MANDATORY_FIELDS
                   if not self[name]]
        if full:
            missing += [label for name, label in self.CARGO_MANDATORY
                        if not self[name]]
            if not self.not_containerised and not self.container_count:
                missing.append("Containers (or tick Not Containerised)")
        if client:
            # the customer record: listed in the banner and demanded at
            # billing, never at the opening (owner, 21/10/2026)
            missing += ["Customer: %s" % label
                        for label in self._client_missing_details()]
        return missing

    @api.depends('customs_regime', 'bl_awb_ref', 'goods_description',
                 'cargo_value', 'package_count', 'weight_kg',
                 'not_containerised', 'container_count', 'partner_id',
                 'partner_id.clearance_invoice_name', 'partner_id.street',
                 'partner_id.vat', 'partner_id.company_registry')
    def _compute_missing_fields(self):
        for file in self:
            missing = file._get_missing_mandatory_fields(client=True)
            file.missing_fields_display = (
                "\n".join("- %s" % m for m in missing) if missing else False)

    def _mandatory_relieved(self):
        """May this file go on with mandatory fields missing?"""
        self.ensure_one()
        if _migrating(self.env) or self.env.context.get('legacy_import'):
            return True
        if self.legacy_id or self.state == 'imported':
            return True
        return self.legacy_relief and not self.completion_required

    def _check_mandatory_complete(self, what, full=None, client=False):
        """The server-side gate every state-changing button runs. The
        full list applies at the start of work and to a file re-opened
        for additional billing; a file that started under the full check
        is held to the invoice essentials afterwards."""
        for file in self:
            if file._mandatory_relieved():
                continue
            # the full list after a re-opening applies to a LEGACY file:
            # a file opened under the strict rule passed it at the start
            missing = file._get_missing_mandatory_fields(
                full=(file.completion_required and file.legacy_relief)
                if full is None else full, client=client)
            if missing:
                raise UserError(self.env._(
                    "%(name)s cannot be %(what)s until every mandatory "
                    "field is filled:%(gap)s  - %(missing)s",
                    name=file.name, what=what, gap=chr(10) * 2,
                    missing=(chr(10) + "  - ").join(missing)))

    # ------------------------------------------------------------------
    # the relief, applied to the gates that already exist
    # ------------------------------------------------------------------
    def _check_ready_to_work(self):
        if self._mandatory_relieved():
            return
        # the base gate first: its messages (regime, cargo, customer
        # record) are the ones the teams know and the tests read
        res = super()._check_ready_to_work()
        self._check_mandatory_complete(self.env._("opened"), full=True)
        return res

    def _check_cargo_described(self):
        if self._mandatory_relieved():
            return
        return super()._check_cargo_described()

    def _check_client_complete(self):
        if self._mandatory_relieved():
            return
        return super()._check_client_complete()

    def _check_client_billable(self):
        if self._mandatory_relieved():
            return
        return super()._check_client_billable()

    def _check_shipment_billable(self):
        if self._mandatory_relieved():
            return
        return super()._check_shipment_billable()

    @api.constrains('bl_awb_ref', 'goods_description', 'cargo_value', 'state')
    def _check_invoice_essentials(self):
        strict = self.filtered(lambda f: not f._mandatory_relieved())
        if strict:
            super(LogisticsFile, strict)._check_invoice_essentials()

    @api.constrains('customs_regime', 'state')
    def _check_customs_regime(self):
        strict = self.filtered(lambda f: not f._mandatory_relieved())
        if strict:
            super(LogisticsFile, strict)._check_customs_regime()

    def action_start_work(self):
        relieved = self.filtered(
            lambda f: f._mandatory_relieved() and not f.customs_regime)
        # The base action refuses a file with no regime before anything
        # else; a relieved file without one starts anyway (acceptance
        # test 1) and the banner keeps saying so.
        for file in relieved:
            if file.state != 'draft':
                raise UserError(self.env._("File %s is not in draft.", file.name))
            if not self.env.su and file.opening_state != 'approved':
                raise UserError(self.env._(
                    "Work cannot start on %s until the Head of Customer "
                    "Service has approved its opening.", file.name))
            if not file.can_start:
                raise UserError(self.env._(
                    "Work cannot start on %(name)s: %(count)s mandatory "
                    "document(s) are still missing and no waiver has been "
                    "approved.", name=file.name,
                    count=file.missing_mandatory_count))
            file.write({'state': 'in_progress',
                        'date_started': fields.Datetime.now()})
        strict = self - relieved
        strict._check_mandatory_complete(self.env._("started"), full=True)
        return super(LogisticsFile, strict).action_start_work() if strict else True

    def action_close_operations(self):
        self._check_mandatory_complete(self.env._("closed for operations"))
        return super().action_close_operations()

    def action_mark_complete(self):
        self._check_mandatory_complete(self.env._("closed"))
        return super().action_mark_complete()

    # ------------------------------------------------------------------
    # the lock
    # ------------------------------------------------------------------
    # What a user may still write on a locked file: the workflow's own
    # stamps and states, the chatter, the billing machinery. Everything
    # a person keys about the job itself is refused.
    LOCK_EXEMPT = frozenset({
        'state', 'billing_status', 'is_locked', 'billing_round',
        'completion_required', 'result_status', 'skip_gain_loss',
        'legacy_relief', 'date_closed', 'date_billed', 'invoice_id',
        'debours_invoice_id', 'billing_split', 'reopen_count',
        'reopening_ids', 'last_reopen_reason_id', 'recharge_amount',
        'recharge_state', 'recharge_note', 'recharge_ops_approved_by_id',
        'recharge_gm_approved_by_id', 'billing_commission_skipped',
        # the billing screen's own figures, persisted and re-persisted
        # on a billed file (a half re-issued, the printed advances)
        'advance_had_amount', 'advance_had_vat_amount', 'advance_other_amount',
        'recharge_comment',
        'message_follower_ids', 'message_ids', 'message_main_attachment_id',
        'activity_ids', 'activity_user_id', 'activity_type_id',
        'activity_date_deadline', 'activity_summary', 'website_message_ids',
        'message_partner_ids', 'rating_ids', 'internal_note',
        'move_ids', 'invoice_ids', 'expense_ids', 'attachment_ids',
        'commercial_invoice_received', 'documents_received_on',
        'manifesting_date', 'manifesting_paid_on', 'delivery_date',
        'transit_start', 'transit_end', 'equivalent_container_count',
        'analytic_account_id', 'user_id', 'stage_owner', 'stage_detail',
        'advance_waiver_state', 'advance_waiver_reason',
        'advance_waiver_approved_by_id', 'advance_waiver_date',
        'reopen_request_state', 'reopen_request_reason',
        'reopen_request_reason_id', 'reopen_request_by_id',
        'reopen_request_date', 'reopen_request_note',
    })
    internal_note = fields.Text(
        string="Internal Note",
        help="The one field that stays writable on a locked file.")

    def _check_not_locked(self, vals):
        if _migrating(self.env) or self.env.context.get('clearance_unlock'):
            return
        touched = set(vals) - self.LOCK_EXEMPT
        if not touched:
            return
        locked = self.filtered('is_locked')
        if locked:
            labels = [self._fields[f].string if f in self._fields else f
                      for f in sorted(touched)]
            raise UserError(self.env._(
                "%(files)s is billed and locked: %(fields)s cannot be "
                "changed. Re-open it for additional billing first - the "
                "Head of Customer Service signs that, with a reason.",
                files=", ".join(locked.mapped('name')),
                fields=", ".join(labels)))

    def write(self, vals):
        self._check_not_locked(vals)
        return super().write(vals)

    def unlink(self):
        if not _migrating(self.env) and any(f.is_locked for f in self):
            raise UserError(self.env._(
                "A billed file is never deleted."))
        return super().unlink()

    # ------------------------------------------------------------------
    # billing: the round, the freeze, the lock
    # ------------------------------------------------------------------
    def _billable_expenses(self):
        # A frozen disbursement belongs to a round already billed. One
        # billed HERE is tracked by its invoice line (is_billed), so a
        # credited or cancelled line makes it billable again, as before;
        # one loaded by the migration has no line, and stays out.
        return super()._billable_expenses().filtered(
            lambda e: not (e.is_frozen and not e.billed_line_id))

    def _create_client_invoice(self, debours, services, split=False):
        # the customer record is _check_client_billable()'s to refuse,
        # with the button to the record (owner 21/10/2026)
        self._check_mandatory_complete(self.env._("billed"))
        invoices = super()._create_client_invoice(debours, services, split=split)
        self._after_billing(invoices)
        return invoices

    def _after_billing(self, invoices):
        """Open the next round and lock the file (brief, section 4)."""
        self.ensure_one()
        new_round = self.billing_round + 1
        billed = self.expense_ids.filtered(
            lambda e: e.billed_line_id and e.billed_line_id.move_id in invoices)
        billed.with_context(clearance_unlock=True).write({
            'billing_round': new_round, 'is_frozen': True})
        invoices.write({'billing_round': new_round})
        # A legacy file's disbursements were debited to the single 471100
        # (owner 20/10/2026), so its invoice credits that account, not
        # the two-account scheme's engaged account the base billing uses.
        legacy_oop = self.company_id.clearance_legacy_oop_account_id
        if self.legacy_relief and legacy_oop:
            invoices.invoice_line_ids.filtered(
                lambda l: l.clearance_category == 'debours'
                and l.account_id != legacy_oop
            ).with_context(clearance_unlock=True).write(
                {'account_id': legacy_oop.id})
        self.with_context(clearance_unlock=True).write({
            'billing_round': new_round,
            'billing_status': 'billed',
            'result_status': ('none' if self.skip_gain_loss
                              or not self.legacy_relief else 'pending'),
        })
        self.message_post(body=self.env._(
            "Billing round %(round)s issued: the file is locked and "
            "%(count)s disbursement(s) are frozen.",
            round=new_round, count=len(billed)))

    def action_reopen_for_billing(self):
        """The button on a locked file: the existing reopen wizard, told
        why it was opened. The Head of Customer Service signs it."""
        self.ensure_one()
        if not self.is_locked:
            raise UserError(self.env._(
                "%s is not locked - nothing to re-open.", self.name))
        action = self.env['ir.actions.act_window']._for_xml_id(
            'elite_clearance.action_logistics_reopen_wizard')
        action['context'] = {'default_file_id': self.id,
                             'clearance_additional_billing': True,
                             'default_target_state': 'in_progress'}
        return action

    def _reopen_for_billing(self, reason, note, target):
        """What re-opening a billed file does beyond the state: the
        earlier items stay frozen, the file is strict from now on, and
        the next bill opens round + 1."""
        self.ensure_one()
        self.with_context(clearance_unlock=True).write({
            'billing_status': 'reopened',
            'completion_required': True,
        })
        self.message_post(body=self.env._(
            "Re-opened for additional billing by %(user)s - %(why)s: "
            "%(note)s. Round %(round)s stays frozen; only new "
            "disbursements and new invoice lines can be added, and the "
            "file is now checked like a new one.",
            user=self.env.user.name, why=reason.name, note=note,
            round=self.billing_round))

    def action_view_journal_entries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Journal Entries - %s", self.name),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('logistics_file_id', '=', self.id)],
            'context': {'default_logistics_file_id': self.id,
                        'search_default_posted': 1},
        }

    # ------------------------------------------------------------------
    # the débours result
    # ------------------------------------------------------------------
    def _debours_lines_billed(self):
        """The débours lines of the file's standing posted invoices and
        credit notes, Handling excluded. Credit notes count negative."""
        self.ensure_one()
        total = 0.0
        # is_legacy: the ZIP importer's drafts, outside every total
        moves = self.invoice_ids.sudo().filtered(
            lambda m: m.state == 'posted' and m._clearance_stands()
            and not m.is_legacy
            and m.move_type in ('out_invoice', 'out_refund'))
        for move in moves:
            sign = -1 if move.move_type == 'out_refund' else 1
            for line in move.invoice_line_ids:
                if line.clearance_category != 'debours' or line.is_handling:
                    continue
                total += sign * line.price_subtotal
        return total

    @api.depends('expense_ids.state', 'expense_ids.amount',
                 'invoice_ids.state', 'invoice_ids.clearance_voided',
                 'invoice_ids.invoice_line_ids.price_subtotal',
                 'move_ids.state')
    def _compute_debours_result(self):
        for file in self:
            incurred = sum(file.expense_ids.filtered(
                lambda e: e.state in INCURRED_STATES and not e.is_legacy
            ).mapped('amount'))
            billed = file._debours_lines_billed()
            file.debours_incurred = incurred
            file.debours_billed = billed
            file.debours_result = billed - incurred
            file.debours_result_posted = file._result_already_posted()

    def _result_moves(self):
        self.ensure_one()
        return self.env['account.move'].sudo().search([
            ('logistics_file_id', '=', self.id),
            ('clearance_entry_type', '=', 'debours_result'),
            ('state', '=', 'posted')])

    def _result_already_posted(self):
        """The net result on the books so far: gains positive, losses
        negative, read off the result entries' P&L lines."""
        self.ensure_one()
        company = self.company_id
        gain, loss = (company.clearance_oop_gain_account_id,
                      company.clearance_oop_loss_account_id)
        total = 0.0
        for move in self._result_moves():
            for line in move.line_ids:
                if gain and line.account_id == gain:
                    total += line.credit - line.debit
                elif loss and line.account_id == loss:
                    total -= line.debit - line.credit
        return total

    def _unpaid_approved_expenses(self):
        self.ensure_one()
        return self.expense_ids.filtered(
            lambda e: e.state in INCURRED_STATES
            and e.state not in PAID_STATES and not e.is_legacy)

    def _evaluate_debours_result(self, post=True):
        """Where the result stands, and post it when it is due
        (brief, 6.4). Idempotent: only the CHANGE since the last posting
        is booked, so running it twice books nothing the second time."""
        for file in self:
            if file.skip_gain_loss or not file.legacy_relief:
                # a file opened after the cutoff books its variance at
                # billing through the recharge adjustment line, not here
                status = 'none'
            elif not file.invoice_ids.sudo().filtered(
                    lambda m: m.state == 'posted' and m._clearance_stands()
                    and not m.is_legacy and m.move_type == 'out_invoice'):
                status = 'not_billed'
            elif file._unpaid_approved_expenses():
                status = 'pending'
            else:
                status = 'due'
            if status == 'due' and post:
                file._post_debours_result()
                status = 'posted'
            elif status == 'due' and file.currency_id.is_zero(
                    file.debours_result - file._result_already_posted()):
                status = 'posted'
            if file.result_status != status:
                # sudo: the accountant confirming a Sage payment may have
                # no write right on the file; the status is the system's
                file.sudo().with_context(clearance_unlock=True).write(
                    {'result_status': status})
        return True

    def _post_debours_result(self):
        """Dr 471100 / Cr 758801 for a gain, Dr 658801 / Cr 471100 for a
        loss - the change since what was already posted."""
        self.ensure_one()
        company = self.company_id
        change = self.debours_result - self._result_already_posted()
        if self.currency_id.is_zero(change):
            return self.env['account.move']
        oop = company.clearance_legacy_oop_account_id
        gain = company.clearance_oop_gain_account_id
        loss = company.clearance_oop_loss_account_id
        journal = company.clearance_misc_journal_id
        if not oop or not gain or not loss or not journal:
            raise UserError(self.env._(
                "Configure the Legacy Débours, Gain on Débours and Loss on "
                "Débours accounts and the Miscellaneous Journal under "
                "Clearance -> Configuration -> Settings before the "
                "débours result of %s can be posted.", self.name))
        amount = abs(change)
        partner = self.partner_id.commercial_partner_id
        billing_dates = self.invoice_ids.sudo().filtered(
            lambda m: m.state == 'posted' and m.move_type == 'out_invoice'
        ).mapped('invoice_date')
        payment_dates = [fields.Date.to_date(e.date_settled)
                         for e in self.expense_ids
                         if e.date_settled and e.state in PAID_STATES]
        when = max([d for d in billing_dates + payment_dates if d]
                   or [fields.Date.context_today(self)])
        ref = "%s - Écart sur débours" % self.name
        if self.billing_round > 1:
            ref += " round %d" % self.billing_round
        analytic = ({str(self.analytic_account_id.id): 100}
                    if self.analytic_account_id else False)
        if change > 0:
            postings = [(oop, amount, 0.0), (gain, 0.0, amount)]
        else:
            postings = [(loss, amount, 0.0), (oop, 0.0, amount)]
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'logistics_file_id': self.id,
            'clearance_entry_type': 'debours_result',
            'billing_round': self.billing_round,
            'date': when,
            'ref': ref,
            'line_ids': [fields.Command.create({
                'name': ref,
                'account_id': account.id,
                'partner_id': partner.id,
                'debit': debit, 'credit': credit,
                'analytic_distribution': analytic,
            }) for account, debit, credit in postings],
        })
        move.action_post()
        # sudo: the accountant who confirmed the payment may not have
        # write on the file, and the note is the system's
        self.sudo().message_post(body=self.env._(
            "Débours result posted (%(ref)s): %(kind)s of %(amount)s - "
            "billed %(billed)s against %(incurred)s incurred.",
            ref=move.name, kind="gain" if change > 0 else "loss",
            amount=amount, billed=self.debours_billed,
            incurred=self.debours_incurred))
        return move

    def action_evaluate_debours_result(self):
        self._evaluate_debours_result(post=True)
        return True

    @api.model
    def _cron_evaluate_debours_results(self):
        """Daily: the files whose result was pending a payment."""
        pending = self.search([('result_status', 'in', ('pending', 'due')),
                               ('legacy_relief', '=', True)])
        pending._evaluate_debours_result(post=True)
        return True

    # ------------------------------------------------------------------
    # migration
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if _migrating(self.env):
            for vals in vals_list:
                vals.setdefault('legacy_relief', True)
            # the checklist comes from the load, not from the template
            self = self.with_context(skip_checklist=True)
        return super(LogisticsFile, self).create(vals_list)

    def action_migration_finalize(self):
        """Called through the API after the load, idempotent: a billed
        file is billed, frozen and locked; its invoices are posted; its
        débours result is evaluated and posted when due."""
        Move = self.env['account.move'].sudo()
        for file in self.with_context(**{MIGRATION: True}):
            invoices = file.invoice_ids.sudo().filtered(
                lambda m: m.move_type in ('out_invoice', 'out_refund')
                and not m.is_legacy and m.state != 'cancel')
            # 1. post every invoice still in draft
            for move in invoices.filtered(lambda m: m.state == 'draft'):
                if move.accounting == 'record_only':
                    continue
                move._clearance_migration_prepare()
                move.action_post()
            # 2. billed files: billed, frozen, locked
            posted = invoices.filtered(
                lambda m: m.state == 'posted' and m.move_type == 'out_invoice'
                and m._clearance_stands())
            if posted:
                round_ = max(invoices.mapped('billing_round') or [0]) or 1
                vals = {}
                if file.billing_status == 'not_billed':
                    vals['billing_status'] = 'billed'
                if not file.billing_round:
                    vals['billing_round'] = round_
                if vals:
                    file.write(vals)
                if not file.invoice_id:
                    file.write({'invoice_id': posted.sorted('invoice_date')[-1].id})
                for move in invoices.filtered(lambda m: not m.billing_round):
                    move.billing_round = round_
                to_freeze = file.expense_ids.filtered(
                    lambda e: not e.is_frozen and e.state != 'cancel'
                    and e.state in INCURRED_STATES)
                to_freeze.write({'is_frozen': True, 'billing_round': round_})
                if file.state not in ('done', 'cancel'):
                    file.write({'state': 'done',
                                'date_closed': file.date_closed
                                or fields.Date.context_today(file)})
            # 3. the result
            file._evaluate_debours_result(post=True)
        return True


# =====================================================================
# The disbursement
# =====================================================================
class LogisticsExpense(models.Model):
    _inherit = 'logistics.expense'

    billing_round = fields.Integer(
        string="Billing Round", default=0, copy=False, readonly=True)
    is_frozen = fields.Boolean(
        string="Frozen", copy=False, readonly=True, index=True,
        help="Billed in a round that is closed: it can no longer be "
             "edited, deleted or billed again.")
    source = fields.Selection(
        [('odoo', "Keyed in Odoo"), ('teese_migration', "TEESE migration")],
        string="Source", default='odoo', required=True, copy=False)
    teese_ref = fields.Char(string="TEESE Advance Code", copy=False, index=True)
    teese_channel = fields.Char(
        string="TEESE Payment Channel", copy=False,
        help="The channel named in the load; mapped to a journal under "
             "Legacy uploads -> Payment Channels.")
    accounting = fields.Selection(
        [('post', "Post the entries"), ('record_only', "Record only")],
        string="Accounting", default='post', required=True, copy=False,
        help="Record only: the payment is already in the general ledger "
             "loaded from Sage (paid on or before the cutoff), so the "
             "disbursement is kept for the file's history and nothing is "
             "posted.")
    target_state = fields.Selection(
        [('submitted', "Submitted"), ('approved', "Approved"),
         ('settlement_submitted', "Settlement submitted"),
         ('settlement_approved', "Settlement approved"),
         ('settled', "Settled (paid)"), ('justified', "Justified"),
         ('cancel', "Cancelled")],
        string="Status to Reach", copy=False,
        help="Given by the migration load: the workflow is replayed up "
             "to this state with the dates given.")
    sage_match = fields.Char(
        string="Sage Match", copy=False,
        help="Migration: the result of the search for this payment in "
             "the Sage general ledger (proposed piece, no match, after "
             "the Sage period).")
    sage_payment_ref = fields.Char(string="Sage Payment Piece", copy=False)
    sage_payment_date = fields.Date(string="Sage Payment Date", copy=False)
    age_days = fields.Integer(
        string="Days Since Approval", compute='_compute_age_days')

    @api.depends('date_approved', 'state')
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for exp in self:
            when = exp.date_approved or exp.date_requested or exp.create_date
            when = fields.Date.to_date(when) if when else None
            exp.age_days = (today - when).days if when else 0

    # ------------------------------------------------------------------
    # the freeze
    # ------------------------------------------------------------------
    FROZEN_FIELDS = frozenset({
        'category_id', 'description', 'amount', 'vendor_id', 'employee_id',
        'collector_id', 'date_requested', 'file_id', 'recharge_amount',
        'recharge_comment', 'billing_name_id', 'manifesting_date',
        'delivery_date', 'quantity', 'unit_label',
    })

    def _check_not_frozen(self, vals):
        if _migrating(self.env) or self.env.context.get('clearance_unlock'):
            return
        touched = set(vals) & self.FROZEN_FIELDS
        if not touched:
            return
        frozen = self.filtered('is_frozen')
        if frozen:
            raise UserError(self.env._(
                "%(refs)s belong(s) to a billing round that is closed and "
                "cannot be changed (%(fields)s). Add a new disbursement in "
                "the new round instead.",
                refs=", ".join(frozen.mapped('name')),
                fields=", ".join(sorted(touched))))

    def write(self, vals):
        # ONE write: the freeze guard first, the migration replay after.
        # (The first build had two `write` methods in this class and the
        # second silently replaced the first - cost one CI cycle.)
        self._check_not_frozen(vals)
        res = super().write(vals)
        if _migrating(self.env) and ('target_state' in vals or 'state' in vals):
            self._migration_replay([vals] * len(self))
        return res

    def _notify_landed(self):
        # seven thousand replayed rows would ring seven thousand bells
        if _migrating(self.env):
            return
        return super()._notify_landed()

    def unlink(self):
        if not _migrating(self.env) and any(e.is_frozen for e in self):
            raise UserError(self.env._(
                "A disbursement billed in a closed round is never deleted."))
        return super().unlink()

    # ------------------------------------------------------------------
    # the legacy posting scheme: one 471100, the customer as partner
    # ------------------------------------------------------------------
    def _legacy_scheme(self):
        self.ensure_one()
        return bool(self.file_id.legacy_relief)

    def _oop_accrual_account(self):
        # no accrual through the supplier on a legacy file (owner 20/10/2026)
        if self._legacy_scheme():
            return self.env['account.account']
        return super()._oop_accrual_account()

    def _legacy_oop_account(self):
        self.ensure_one()
        return self._get_company_account(
            'clearance_legacy_oop_account_id', "Legacy Débours (471100) account")

    def _misc_journal(self):
        self.ensure_one()
        journal = self.company_id.clearance_misc_journal_id
        if not journal:
            journal = self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('company_id', '=', self.company_id.id)], limit=1)
        if not journal:
            raise UserError(self.env._(
                "Configure the Clearance Miscellaneous Journal in Settings."))
        return journal

    def _post_legacy_settlement(self, when=None):
        """Dr 471100 (customer, file) / Cr the channel for a payment to
        the payee; Dr 421101 (employee) / Cr the channel for a staff
        advance. Nothing for record_only."""
        self.ensure_one()
        if self.accounting == 'record_only':
            return self.env['account.move']
        if not self.journal_id:
            raise UserError(self.env._(
                "Choose the payment channel on %s.", self.name))
        advance = (self.payment_mode == 'advance'
                   and self.justification_required)
        customer = self.file_id.partner_id.commercial_partner_id
        if advance:
            debit_account = self._get_company_account(
                'clearance_advance_account_id', "Employee Advances account")
            partner = self.employee_id._clearance_auxiliary_partner()
        else:
            debit_account = self._legacy_oop_account()
            partner = customer
        credit_account = self._payment_credit_account()
        label = self._ledger_label()
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'logistics_file_id': self.file_id.id,
            'clearance_entry_type': 'payment',
            'date': when or fields.Date.context_today(self),
            'ref': "%s — %s" % (self.name, label),
            'line_ids': [
                fields.Command.create({
                    'name': label, 'account_id': debit_account.id,
                    'partner_id': partner.id if partner else False,
                    'debit': self.amount, 'credit': 0.0,
                    'analytic_distribution': self._analytic_distribution()}),
                fields.Command.create({
                    'name': label, 'account_id': credit_account.id,
                    'partner_id': (self.vendor_id or partner).id
                    if (self.vendor_id or partner) else False,
                    'debit': 0.0, 'credit': self.amount,
                    'analytic_distribution': self._analytic_distribution()}),
            ],
        })
        move.action_post()
        return move

    def _post_legacy_justification(self, when=None):
        """Dr 471100 (customer, file) / Cr 421101 (employee)."""
        self.ensure_one()
        if self.accounting == 'record_only':
            return self.env['account.move']
        if self.payment_mode != 'advance' or not self.justification_required:
            return self.env['account.move']
        oop = self._legacy_oop_account()
        adv = self._get_company_account(
            'clearance_advance_account_id', "Employee Advances account")
        holder = self.employee_id._clearance_auxiliary_partner()
        customer = self.file_id.partner_id.commercial_partner_id
        label = self._ledger_label()
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': self._misc_journal().id,
            'logistics_file_id': self.file_id.id,
            'clearance_entry_type': 'justification',
            'date': when or fields.Date.context_today(self),
            'ref': "Justification %s — %s" % (self.name, label),
            'line_ids': [
                fields.Command.create({
                    'name': label, 'account_id': oop.id,
                    'partner_id': customer.id,
                    'debit': self.amount, 'credit': 0.0,
                    'analytic_distribution': self._analytic_distribution()}),
                fields.Command.create({
                    'name': label, 'account_id': adv.id,
                    'partner_id': holder.id if holder else False,
                    'debit': 0.0, 'credit': self.amount}),
            ],
        })
        move.action_post()
        return move

    def action_settle(self):
        """A disbursement keyed in Odoo on a legacy file pays through the
        single 471100 (owner 20/10/2026); every other file keeps the
        two-account scheme of the base action."""
        legacy = self.filtered(lambda e: e._legacy_scheme())
        for exp in legacy:
            exp._check_disburser()
            if exp.state != 'settlement_approved':
                raise UserError(self.env._(
                    "The settlement of %s has not been approved by the "
                    "Head of Service Finance.", exp.name))
            if (not self.env.su and not exp.payment_evidence_ids
                    and exp.journal_id.type != 'cash'):
                raise UserError(self.env._(
                    "Attach the payment evidence for %s before it is paid "
                    "out.", exp.name))
            move = exp._post_legacy_settlement()
            exp.write({
                'settlement_move_id': move.id or False,
                'state': 'settled',
                'date_settled': fields.Datetime.now(),
                'settled_by_id': self.env.user.id,
            })
            if exp.journal_id.type == 'cash':
                exp._issue_cash_voucher()
        rest = self - legacy
        return super(LogisticsExpense, rest).action_settle() if rest else True

    def action_justify_finance(self):
        legacy = self.filtered(lambda e: e._legacy_scheme())
        for exp in legacy:
            exp.company_id._clearance_check_approver('justification_finance')
            if exp.state != 'justification_ops_approved':
                raise UserError(self.env._(
                    "%s has not been accepted by Operations yet.", exp.name))
            move = exp._post_legacy_justification()
            exp.sudo().write({'justification_move_id': move.id or False,
                              'state': 'justified',
                              'date_justified': fields.Datetime.now()})
            exp.message_post(body=self.env._(
                "Advance justified: %(amount)s reclassified from 421101 "
                "(held by %(who)s) to the legacy débours account.",
                amount=exp.amount, who=exp.employee_id.name))
            exp.file_id._evaluate_debours_result()
        rest = self - legacy
        return super(LogisticsExpense, rest).action_justify_finance() if rest else True

    # ------------------------------------------------------------------
    # the accountant's actions on an approved disbursement nobody paid
    # ------------------------------------------------------------------
    def _check_awaiting_payment(self):
        for exp in self:
            if exp.state not in ('approved', 'settlement_submitted',
                                 'settlement_approved') or exp.settlement_move_id:
                raise UserError(self.env._(
                    "%s is not an approved disbursement awaiting payment.",
                    exp.name))

    def action_open_sage_payment_wizard(self):
        self.ensure_one()
        self._check_awaiting_payment()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Confirm the Sage payment"),
            'res_model': 'clearance.sage.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_expense_id': self.id,
                        'default_sage_payment_ref': self.sage_payment_ref
                        or (self.sage_match if self.sage_match
                            and self.sage_match.lower() not in
                            ('no match', 'after sage period') else False),
                        'default_sage_payment_date': self.sage_payment_date},
        }

    def action_confirm_sage_payment(self, ref, when):
        """The payment is in the Sage ledger already: settle (or justify,
        for a staff advance on a billed file) with accounting =
        record_only, post nothing, re-evaluate the file (brief 6.5)."""
        for exp in self:
            exp.company_id._clearance_check_approver('sage_confirm')
            exp._check_awaiting_payment()
            if not ref or not when:
                raise UserError(self.env._(
                    "Give the Sage piece and its date."))
            advance = (exp.payment_mode == 'advance'
                       and exp.justification_required)
            billed = exp.file_id.billing_status != 'not_billed'
            stamp = fields.Datetime.to_datetime(when)
            vals = {
                'accounting': 'record_only',
                'sage_payment_ref': ref,
                'sage_payment_date': when,
                'state': 'justified' if advance and billed else 'settled',
                'date_settled': stamp,
                'settled_by_id': self.env.user.id,
            }
            if advance and billed:
                vals['date_justified'] = stamp
            exp.with_context(clearance_unlock=True).write(vals)
            exp.message_post(body=self.env._(
                "Payment confirmed from the Sage ledger by %(user)s: piece "
                "%(ref)s of %(date)s. Nothing posted here - the entry is "
                "in the loaded general ledger.",
                user=self.env.user.name, ref=ref, date=when))
            exp.file_id._evaluate_debours_result()
        return True

    def action_cancel_approval(self):
        """The expense was never needed (brief 6.5). Reason required,
        through the rejection dialog."""
        reason = self._clearance_rejection_reason()
        for exp in self:
            exp.company_id._clearance_check_approver('sage_confirm')
            exp._check_awaiting_payment()
            if not reason and not self.env.su:
                raise UserError(self.env._(
                    "Give the reason for cancelling the approval of %s.",
                    exp.name))
            exp.with_context(clearance_unlock=True).write({'state': 'cancel'})
            exp._clearance_post_rejection(
                self.env._("Approval cancelled by %(user)s: %(why)s",
                           user=self.env.user.name,
                           why=reason or "no reason given"),
                exp.create_uid.partner_id)
            exp.file_id._evaluate_debours_result()
        return True

    # ------------------------------------------------------------------
    # migration: replay the workflow up to target_state
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if not _migrating(self.env):
            return super().create(vals_list)
        for vals in vals_list:
            vals.setdefault('source', 'teese_migration')
            vals.setdefault('originating_team', False)
            vals.setdefault('date_requested', vals.get('date_submitted')
                            or fields.Date.context_today(self))
        # sudo: the originating-team gate is su-exempt, and the load runs
        # as an administrator who is not a team; legacy_import: the file
        # is in whatever state history left it
        records = super(LogisticsExpense, self.sudo().with_context(
            legacy_import=True)).create(vals_list)
        records._migration_replay(vals_list)
        return records.with_env(self.env)

    def _migration_replay(self, vals_list):
        """Walk the states up to target_state, stamping the dates given
        and posting what a `post` row posts, at the row's own dates."""
        for exp, vals in zip(self, vals_list):
            target = exp.target_state or vals.get('target_state')
            if not target:
                continue
            if target == 'cancel':
                if exp.state != 'cancel':
                    super(LogisticsExpense, exp).write({'state': 'cancel'})
                continue
            if exp.teese_channel and not exp.journal_id:
                journal = self.env['clearance.payment.channel']._journal_for(
                    exp.teese_channel, exp.company_id)
                if journal:
                    super(LogisticsExpense, exp).write({'journal_id': journal.id})
            if (STATE_RANK.get(target, 0) >= STATE_RANK['settled']
                    and exp.payment_mode != 'advance' and not exp.journal_id
                    and exp.accounting == 'post'):
                raise UserError(self.env._(
                    "%(ref)s is to be loaded as paid and posted but names "
                    "no payment channel.", ref=exp.teese_ref or exp.name))
            if exp.payment_mode == 'advance' and not exp.employee_id:
                raise UserError(self.env._(
                    "%(ref)s is a staff advance with no holder.",
                    ref=exp.teese_ref or exp.name))
            current = STATE_RANK.get(exp.state, 0)
            wanted = STATE_RANK[target]
            if wanted < STATE_RANK['justified'] and target == 'justified':
                wanted = STATE_RANK['justified']
            for state, stamp_field, who_field in REPLAY_STEPS:
                rank = STATE_RANK[state]
                if rank <= current or rank > wanted:
                    continue
                if (state in ('justification_submitted',
                              'justification_ops_approved', 'justified')
                        and not (exp.payment_mode == 'advance'
                                 and exp.justification_required)):
                    # a payment to a payee stops at settled
                    break
                update = {'state': state}
                if stamp_field and not exp[stamp_field]:
                    # the load gives the dates it has; a missing one is
                    # stamped at the moment of the load
                    update[stamp_field] = fields.Datetime.now()
                if who_field and not exp[who_field]:
                    update[who_field] = self.env.user.id
                if state == 'settled':
                    when = fields.Date.to_date(exp.date_settled) if exp.date_settled else None
                    move = exp._post_legacy_settlement(when=when)
                    if move:
                        update['settlement_move_id'] = move.id
                if state == 'justified':
                    when = fields.Date.to_date(exp.date_justified) if exp.date_justified else None
                    move = exp._post_legacy_justification(when=when)
                    if move:
                        update['justification_move_id'] = move.id
                super(LogisticsExpense, exp.with_context(
                    clearance_no_notify=True)).write(update)


# =====================================================================
# The invoice and its lines
# =====================================================================
class AccountMove(models.Model):
    _inherit = 'account.move'

    clearance_entry_type = fields.Selection(
        [('invoice', "Invoice / credit note"),
         ('payment', "Disbursement payment"),
         ('accrual', "Disbursement accrual"),
         ('justification', "Advance justification"),
         ('debours_result', "Débours result")],
        string="Clearance Entry", copy=False, index=True)
    document_type = fields.Selection(
        [('invoice', "Invoice"), ('debit_note', "Debit note"),
         ('credit_note', "Credit note")],
        string="Document Type", compute='_compute_document_type',
        store=True, readonly=False, copy=False)
    accounting = fields.Selection(
        [('post', "Post"), ('record_only', "Record only")],
        string="Accounting", default='post', copy=False,
        help="Always Post for the migration: every TEESE invoice is "
             "posted, whatever its date.")
    teese_ref = fields.Char(string="TEESE Reference", copy=False, index=True)
    billing_round = fields.Integer(string="Billing Round", copy=False)

    @api.depends('move_type')
    def _compute_document_type(self):
        for move in self:
            if move.document_type:
                continue
            if move.move_type == 'out_refund':
                move.document_type = 'credit_note'
            elif move.move_type == 'out_invoice':
                move.document_type = 'invoice'
            else:
                move.document_type = False

    def _clearance_migration_prepare(self):
        """Before posting a loaded invoice: the accounts its lines land
        on, decided by the line's clearance category and never by the
        load (brief 6.1), and the XAF rounding on each line."""
        for move in self:
            move.invoice_line_ids._clearance_migration_accounts()
            if move.logistics_file_id and not move.clearance_entry_type:
                move.clearance_entry_type = 'invoice'

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        files = self.env['logistics.file']
        for move in posted.filtered('logistics_file_id'):
            if not move.clearance_entry_type and move.move_type in (
                    'out_invoice', 'out_refund'):
                move.clearance_entry_type = 'invoice'
            if move.move_type in ('out_invoice', 'out_refund'):
                files |= move.logistics_file_id
        for file in files:
            file._evaluate_debours_result()
        return posted

    def button_draft(self):
        locked = self.filtered(
            lambda m: m.logistics_file_id.is_locked
            and m.move_type in ('out_invoice', 'out_refund'))
        if locked and not _migrating(self.env):
            raise UserError(self.env._(
                "%s belongs to a billed and locked file. A posted invoice "
                "on it is corrected by a credit note, never reset to "
                "draft.", ", ".join(locked.mapped('name'))))
        return super().button_draft()

    @api.model_create_multi
    def create(self, vals_list):
        if _migrating(self.env):
            for vals in vals_list:
                if vals.get('move_type') in ('out_invoice', 'out_refund'):
                    vals.setdefault('clearance_entry_type', 'invoice')
                    if vals.get('document_type') == 'credit_note' and \
                            vals.get('move_type') == 'out_invoice':
                        vals['move_type'] = 'out_refund'
        return super().create(vals_list)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # Only the flag counts (Handling brief, 20/10/2026): a billing
    # component carries it, billing copies it on to the line, a migrated
    # line brings it from the load file. The description is never read.
    is_handling = fields.Boolean(
        string="Handling", copy=False, index=True,
        help="Handling billed and due back to the customer: credited to "
             "the customer's receivable account (or the Handling account "
             "in Settings), no VAT, matched against the invoice inside "
             "the entry, and outside the débours result on both sides.")
    legacy_id = fields.Integer(string="Legacy Line ID", index=True, copy=False)

    def _clearance_migration_accounts(self):
        """The account per line category, from the settings - and NO tax
        on any line: a migrated invoice carries its TEESE VAT as its own
        `vat` line, so the entry totals exactly what TEESE invoiced.
        The clearing comes AFTER the account is set, because Odoo
        recomputes a line's taxes from the account's default taxes
        whenever the account changes (owner, 23/10/2026)."""
        for line in self:
            if line.display_type in ('line_section', 'line_note'):
                continue
            company = line.company_id or line.move_id.company_id
            file = line.move_id.logistics_file_id
            account = False
            cat = line.clearance_category
            if line.is_handling:
                # due back to the customer, whatever block it was billed in
                account = company._clearance_handling_account(
                    line.move_id.partner_id)
            elif cat == 'debours':
                account = (company.clearance_legacy_oop_account_id
                           if file.legacy_relief
                           else company.clearance_oop_account_id)
            elif cat == 'vat':
                account = company.clearance_vat_account_id
            elif cat == 'prestation':
                kind = line.clearance_service_kind
                account = (
                    company.clearance_commission_account_id if kind == 'commission'
                    else company.clearance_service_fee_account_id if kind == 'customs_fee'
                    else company.clearance_file_fee_account_id if kind == 'file_fee'
                    else False) or company.clearance_fee_account_id
            if account and line.account_id != account:
                line.account_id = account
            # reading tax_ids here runs Odoo's recompute from the new
            # account first; the clearing then wins
            if line.tax_ids:
                line.tax_ids = [fields.Command.clear()]

    def write(self, vals):
        if not _migrating(self.env) and not self.env.context.get('clearance_unlock'):
            business = {'price_unit', 'quantity', 'name', 'account_id',
                        'tax_ids', 'clearance_adjustment', 'discount'}
            if business & set(vals):
                frozen = self.filtered(
                    lambda l: l.move_id.logistics_file_id.is_locked
                    and l.move_id.move_type in ('out_invoice', 'out_refund')
                    and l.move_id.state == 'posted')
                if frozen:
                    raise UserError(self.env._(
                        "The lines of %s belong to a billed and locked "
                        "file and cannot be changed.",
                        ", ".join(frozen.mapped('move_id.name'))))
        return super().write(vals)


# =====================================================================
# The accountant's dialog
# =====================================================================
class ClearanceSagePaymentWizard(models.TransientModel):
    _name = 'clearance.sage.payment.wizard'
    _description = "Confirm a Sage Payment"

    expense_id = fields.Many2one('logistics.expense', required=True, readonly=True)
    amount = fields.Monetary(related='expense_id.amount')
    currency_id = fields.Many2one(related='expense_id.currency_id')
    sage_match = fields.Char(related='expense_id.sage_match')
    sage_payment_ref = fields.Char(string="Sage Piece", required=True)
    sage_payment_date = fields.Date(string="Paid On", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.expense_id.action_confirm_sage_payment(
            self.sage_payment_ref, self.sage_payment_date)
        return {'type': 'ir.actions.act_window_close'}
