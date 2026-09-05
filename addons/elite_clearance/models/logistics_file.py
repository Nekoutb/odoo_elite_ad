from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class LogisticsFile(models.Model):
    """A clearance job file — the object the whole workflow hangs on.

    One file = one clearance instruction from one client. Out-of-pocket
    expenses, cash advances and the client invoice all point at this record
    and carry its analytic account, which is what makes per-file
    profitability fall out of the accounting.
    """

    _name = 'logistics.file'
    _description = "Clearance File"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_opened desc, create_date desc, id desc'
    _rec_names_search = ['name', 'partner_id.name', 'customs_declaration_ref']

    # --- identification -------------------------------------------------
    name = fields.Char(
        string="File Reference", required=True, copy=False, readonly=True,
        default="New", index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string="Client", required=True, index=True,
        tracking=True, domain="[('is_company', '=', True)]",
    )
    partner_slug = fields.Char(
        related='partner_id.clearance_slug', string="Client Slug",
        readonly=True,
        help="The client's three letters, as they appear in this file's "
             "analytic tag. Assigned when the client's first file is opened.")
    service_type_id = fields.Many2one(
        'logistics.service.type', string="Service Type", required=True,
        tracking=True,
    )
    user_id = fields.Many2one(
        'res.users', string="Responsible", tracking=True,
        default=lambda self: self.env.user, domain="[('share', '=', False)]",
    )
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )

    # --- operational references ----------------------------------------
    transit_authorisation_ref = fields.Char(
        string="Transit Order / Authorisation", tracking=True,
        help="The client's transit order or authorisation to act.",
    )
    customs_regime = fields.Selection(
        [('im4', "IM4 - Mise à la consommation"),
         ('im5', "IM5 - Admission temporaire"),
         ('im7', "IM7 - Entrepôt"),
         ('im8', "IM8 - Transit")],
        string="Customs Regime", tracking=True, index=True,
        help="The regime declared to Customs. It decides what the file is "
             "for, so it is chosen when the file is opened and cannot be "
             "left blank once work starts.")
    customs_declaration_ref = fields.Char(string="Customs Declaration", tracking=True)
    bl_awb_ref = fields.Char(string="BL / AWB")
    date_opened = fields.Date(
        string="Opened On", default=fields.Date.context_today, required=True,
    )
    date_target = fields.Date(string="Target Clearance Date", tracking=True)
    date_closed = fields.Date(string="Closed On", readonly=True, copy=False)
    # The clock the reporting section reads. Every one of these is written
    # by the action that performs the step, never by hand, so a turnaround
    # figure is a record of what happened rather than what was typed.
    date_started = fields.Datetime(
        string="Work Started", readonly=True, copy=False)
    date_ops_closed = fields.Datetime(
        string="Closed for Operations", readonly=True, copy=False)
    date_billed = fields.Datetime(
        string="Invoiced On", readonly=True, copy=False)
    note = fields.Html(string="Internal Notes")

    # --- cargo & routing (from the legacy dossier) -----------------------
    port_id = fields.Many2one('logistics.port', string="Port", tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string="Follow-up Employee", tracking=True,
        help="The staff member who follows the file day to day. Distinct "
             "from the Responsible user: not every declarant has a login.")
    shipment_type = fields.Selection(
        [('container', "Container"),
         ('conventional', "Conventional / break-bulk"),
         ('flatbed', "Flatbed truck")],
        string="Shipment Type")
    container_count = fields.Integer(string="Containers")
    package_count = fields.Integer(string="Packages")
    weight_kg = fields.Float(string="Weight (kg)", digits=(16, 3))
    cargo_value = fields.Monetary(
        string="Cargo Value", currency_field='currency_id',
        help="Declared value of the goods.")
    legacy_customs_regime = fields.Char(
        string="Legacy Regime", readonly=True, copy=False,
        help="Whatever Teese recorded as the regime, kept verbatim. New "
             "files use the Customs Regime field, which is a closed list.")
    container_type = fields.Char(
        string="Container Type", help="e.g. 20, 40, 40HC.")
    goods_description = fields.Char(
        string="Goods", help="Printed on the invoice as Produits.")
    supplier_name = fields.Char(
        string="Supplier", help="The shipper or supplier, printed on the "
                                "invoice as Fournisseur.")
    client_reference = fields.Char(
        string="Client Reference",
        help="The client's own reference for this shipment.")
    cargo_value_currency_id = fields.Many2one(
        'res.currency', string="Cargo Value Currency",
        help="The currency the declared value is expressed in - often not "
             "XAF. Empty prints in the company currency.")
    incoterm_id = fields.Many2one('account.incoterms', string="Incoterm")
    importer_name = fields.Char(
        string="Importer",
        help="The importer of record when it is not the client.")

    # --- legacy (Teese) provenance -------------------------------------
    legacy_id = fields.Integer(
        string="Legacy ID", index=True, copy=False,
        help="Identifier of this dossier in the legacy Teese system. Set "
             "only by the migration; makes re-imports idempotent.")
    legacy_type_name = fields.Char(
        string="Legacy Type", copy=False,
        help="The dossier type exactly as the legacy system labelled it, "
             "kept because the mapping to a service type is a judgement.")

    # --- analytic -------------------------------------------------------
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string="Analytic Account",
        readonly=True, copy=False, ondelete='restrict',
        help="Created automatically with the file. Every cost and revenue "
             "posted later carries this tag, which is what makes per-file "
             "profitability possible.",
    )

    # --- workflow -------------------------------------------------------
    state = fields.Selection(
        [
            ('draft', "Draft"),
            ('in_progress', "In Progress"),
            ('ops_closed', "OK for Billing"),
            ('done', "Complete"),
            ('imported', "Imported"),
            ('cancel', "Cancelled"),
        ],
        default='draft', required=True, tracking=True, index=True,
        help="Imported: brought over from the legacy system as a record. "
             "No work or billing happens on it unless the billing agent "
             "asks to reopen it and an Operations Manager approves.",
    )

    # --- reopening an imported file -------------------------------------
    reopen_request_state = fields.Selection(
        [
            ('none', "Not requested"),
            ('requested', "Awaiting Operations Manager"),
            ('approved', "Approved"),
            ('refused', "Refused"),
        ],
        default='none', required=True, tracking=True, copy=False,
        string="Reopening Request")
    reopen_request_reason = fields.Text(
        string="Why reopen this imported file", copy=False,
        help="What remains to be done or billed on a file the legacy system "
             "considered live, and why it should be worked in Odoo.")
    reopen_requested_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    reopen_approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    reopen_request_date = fields.Datetime(readonly=True, copy=False)

    # --- document checklist ---------------------------------------------
    document_ids = fields.One2many(
        'logistics.file.document', 'file_id', string="Document Checklist",
    )
    missing_mandatory_count = fields.Integer(
        compute='_compute_document_status', store=True,
        string="Missing Mandatory Documents",
    )
    documents_complete = fields.Boolean(
        compute='_compute_document_status', store=True,
        string="Documentation Complete",
    )

    # --- waiver (start work without full documentation) -----------------
    waiver_state = fields.Selection(
        [
            ('none', "Not requested"),
            ('requested', "Awaiting approval"),
            ('approved', "Approved"),
            ('refused', "Refused"),
        ],
        default='none', required=True, tracking=True, string="Waiver",
        copy=False,
    )
    waiver_reason = fields.Text(
        string="Waiver Justification", copy=False,
        help="Why work should begin before all mandatory documents are in.",
    )
    waiver_requested_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    waiver_approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    waiver_date = fields.Datetime(readonly=True, copy=False)
    waiver_requested_date = fields.Datetime(readonly=True, copy=False)

    can_start = fields.Boolean(compute='_compute_can_start')

    # --- out-of-pocket expenses & billing -------------------------------
    expense_ids = fields.One2many('logistics.expense', 'file_id', string="Expenses")
    expense_count = fields.Integer(compute='_compute_expense_count')
    oop_total = fields.Monetary(
        compute='_compute_oop_total', store=True,
        string="Out-of-Pocket Total", currency_field='currency_id',
        help="Direct expenses settled plus advances justified — the amount "
             "sitting on the out-of-pocket account for this file.",
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    commission_rate = fields.Float(
        related='service_type_id.commission_rate', string="Commission Rate (%)")
    billing_commission_rate = fields.Float(
        string="Billed Commission Rate (%)", digits=(6, 3), readonly=True,
        help="The rate the billing agent actually used, kept once the file "
             "is billed. Zero means the service type's own rate was used.")
    commission_amount = fields.Monetary(
        compute='_compute_fee_amounts', store=True, currency_field='currency_id',
        string="Commission (on OOP)")
    customs_fee_amount = fields.Monetary(
        string="Customs Service Fee", currency_field='currency_id', tracking=True,
        help="Keyed by the billing agent from the customs declaration.")
    unjustified_advance_total = fields.Monetary(
        compute='_compute_unjustified_advance_total', store=True,
        currency_field='currency_id', string="Unjustified Staff Advances",
        help="Advanced to staff and settled, but not yet justified with "
             "supporting documents — still on 421101 against the holder. "
             "This is NOT billable and blocks the file until justified or "
             "waived.")
    advance_waiver_state = fields.Selection(
        [
            ('none', "Not requested"),
            ('requested', "Awaiting approval"),
            ('approved', "Approved"),
            ('refused', "Refused"),
        ],
        default='none', required=True, tracking=True, copy=False,
        string="Unjustified Advance Waiver")
    advance_waiver_reason = fields.Text(
        string="Advance Waiver Explanation", copy=False,
        help="Why this file should be billed while a staff advance is still "
             "unsupported, and how the advance will be recovered.")
    advance_waiver_requested_by_id = fields.Many2one(
        'res.users', readonly=True, copy=False)
    advance_waiver_approved_by_id = fields.Many2one(
        'res.users', readonly=True, copy=False)
    advance_waiver_date = fields.Datetime(readonly=True, copy=False)
    advance_waiver_requested_date = fields.Datetime(readonly=True, copy=False)
    # --- recharging the client at other than cost -----------------------
    advance_had_amount = fields.Monetary(
        string="Advance HAD/DAU", currency_field='currency_id', readonly=True,
        help="Already advanced by the client against the customs fee. Set "
             "on the billing screen and deducted on the invoice.")
    advance_had_vat_amount = fields.Monetary(
        string="Advance VAT on HAD/DAU", currency_field='currency_id',
        readonly=True)
    advance_other_amount = fields.Monetary(
        string="Other Advances", currency_field='currency_id', readonly=True)
    invoice_balance_due = fields.Monetary(
        compute='_compute_invoice_balance_due', currency_field='currency_id',
        string="Balance Due")

    recharge_amount = fields.Monetary(
        string="Recharge to the Client", currency_field='currency_id',
        tracking=True, copy=False,
        help="What the client is actually charged for disbursements. Left at "
             "zero the invoice recharges at cost; any other figure is an "
             "adjustment and has to be approved before the invoice is raised.")
    recharge_variance = fields.Monetary(
        compute='_compute_recharge_variance', store=True,
        currency_field='currency_id', string="Adjustment vs Cost",
        help="Positive: the client is charged more than was disbursed. "
             "Negative: the company is absorbing part of the cost.")
    recharge_reason = fields.Text(
        string="Why the recharge differs from cost", copy=False)
    recharge_state = fields.Selection(
        [
            ('none', "At cost"),
            ('requested', "Awaiting Operations Manager"),
            ('ops_approved', "Awaiting General Manager"),
            ('approved', "Approved"),
            ('refused', "Refused"),
        ],
        default='none', required=True, tracking=True, copy=False,
        string="Recharge Adjustment")
    recharge_ops_approved_by_id = fields.Many2one(
        'res.users', readonly=True, copy=False, string="Operations Approval")
    recharge_gm_approved_by_id = fields.Many2one(
        'res.users', readonly=True, copy=False, string="General Manager Approval")
    recharge_approved_date = fields.Datetime(readonly=True, copy=False)
    recharge_requested_date = fields.Datetime(readonly=True, copy=False)
    invoice_id = fields.Many2one(
        'account.move', string="Client Invoice", readonly=True, copy=False)
    invoice_state = fields.Selection(related='invoice_id.state', string="Invoice Status")
    invoice_ids = fields.One2many(
        'account.move', 'logistics_file_id', string="Client Invoices",
        domain=[('move_type', 'in', ('out_invoice', 'out_refund'))])
    invoice_count = fields.Integer(compute='_compute_invoice_count')
    # Billing done in the legacy system: draft invoices that can never be
    # posted, flagged is_legacy on account.move. Totals here read the Teese
    # figures, so the file shows revenue and disbursements side by side.
    legacy_invoice_count = fields.Integer(compute='_compute_legacy_billing')
    legacy_billed_total = fields.Monetary(
        compute='_compute_legacy_billing', currency_field='currency_id',
        string="Imported Billing (Teese TTC)")
    legacy_outstanding_total = fields.Monetary(
        compute='_compute_legacy_billing', currency_field='currency_id',
        string="Imported Outstanding at Export")
    legacy_expense_total = fields.Monetary(
        compute='_compute_legacy_billing', currency_field='currency_id',
        string="Imported Disbursements (Teese)",
        help="Advances the legacy system disbursed on this file, excluding "
             "reversals. Not posted here; shown so that what was spent and "
             "what was billed can be read together.")
    reopen_count = fields.Integer(readonly=True, copy=False)

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        "A clearance file with this reference already exists.",
    )

    # =====================================================================
    # Computes
    # =====================================================================
    @api.depends('document_ids.is_mandatory', 'document_ids.received')
    def _compute_document_status(self):
        for file in self:
            missing = file.document_ids.filtered(
                lambda d: d.is_mandatory and not d.received
            )
            file.missing_mandatory_count = len(missing)
            file.documents_complete = not missing

    # expense_count and oop_total are deliberately computed by two separate
    # methods. One method feeding both would mix a stored field with a
    # non-stored one, and Odoo 19 warns on every registry load that reading
    # the cheap counter can trigger a recompute-and-write of the total.
    @api.depends('expense_ids')
    def _compute_expense_count(self):
        counts = dict(self.env['logistics.expense']._read_group(
            domain=[('file_id', 'in', self.ids)],
            groupby=['file_id'],
            aggregates=['__count'],
        ))
        for file in self:
            file.expense_count = counts.get(file, 0)

    @api.depends('expense_ids.state', 'expense_ids.amount',
                 'expense_ids.payment_mode', 'expense_ids.is_legacy')
    def _compute_oop_total(self):
        # Legacy expenses were billed in the old system and carry no posting
        # here: they never feed a new invoice.
        for file in self:
            file.oop_total = sum(
                e.amount for e in file.expense_ids
                if not e.is_legacy and (
                    e.state == 'justified'
                    or (e.state == 'settled' and e.payment_mode != 'advance')))

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for file in self:
            file.invoice_count = len(file.invoice_ids)

    @api.depends('invoice_ids.is_legacy', 'invoice_ids.legacy_amount_total',
                 'invoice_ids.legacy_amount_residual',
                 'expense_ids.is_legacy', 'expense_ids.amount', 'expense_ids.state')
    def _compute_legacy_billing(self):
        for file in self:
            invs = file.invoice_ids.filtered('is_legacy')
            file.legacy_invoice_count = len(invs)
            file.legacy_billed_total = sum(invs.mapped('legacy_amount_total'))
            file.legacy_outstanding_total = sum(invs.mapped('legacy_amount_residual'))
            file.legacy_expense_total = sum(
                e.amount for e in file.expense_ids
                if e.is_legacy and e.state != 'cancel')

    @api.depends('expense_ids.state', 'expense_ids.amount',
                 'expense_ids.payment_mode')
    def _compute_unjustified_advance_total(self):
        for file in self:
            file.unjustified_advance_total = sum(
                e.amount for e in file.expense_ids
                if not e.is_legacy
                and e.payment_mode == 'advance' and e.state == 'settled')

    @api.depends('recharge_amount', 'oop_total')
    def _compute_recharge_variance(self):
        for file in self:
            file.recharge_variance = (
                file.recharge_amount - file.oop_total
                if file.recharge_amount else 0.0)

    def write(self, vals):
        # Only a figure that actually MOVES is a new request. Re-writing the
        # same number - which the billing screen does every time it saves -
        # must not tear up an approval that was given for exactly it.
        resync = self.browse()
        if 'recharge_amount' in vals and not self.env.context.get(
                'clearance_recharge_sync'):
            proposed = vals['recharge_amount'] or 0.0
            resync = self.filtered(
                lambda f: f.currency_id.compare_amounts(
                    f.recharge_amount, proposed))
        res = super().write(vals)
        for file in resync:
            file._sync_recharge_state()
        return res

    def _sync_recharge_state(self):
        """Changing the figure IS the request.

        The first version made this a button, and a button nobody presses is
        a control that does not exist: the owner adjusted 50,000 to 45,000
        and nothing happened. Editing the recharge now puts the file into
        approval by itself, and any approval already given is torn up,
        because it was given for a different number.
        """
        self.ensure_one()
        variance = (self.recharge_amount - self.oop_total
                    if self.recharge_amount else 0.0)
        target = 'none' if self.currency_id.is_zero(variance) else 'requested'
        if self.recharge_state == target and target == 'none':
            return
        self.with_context(clearance_recharge_sync=True).write({
            'recharge_state': target,
            'recharge_requested_date': (
                fields.Datetime.now() if target == 'requested' else False),
            'recharge_ops_approved_by_id': False,
            'recharge_gm_approved_by_id': False,
            'recharge_approved_date': False,
        })
        if target == 'requested':
            self.message_post(body=self.env._(
                "Recharge set to %(amount)s against a cost of %(cost)s "
                "(%(variance)s). It needs approval before this file can be "
                "billed, and any approval already given has lapsed.",
                amount=self.recharge_amount, cost=self.oop_total,
                variance=variance))
        else:
            self.message_post(body=self.env._(
                "Recharge back at cost; no approval needed."))

    def _recharge_total(self):
        """What the invoice actually recharges: cost, unless an adjustment
        has been approved."""
        self.ensure_one()
        if self.recharge_state == 'approved' and self.recharge_amount:
            return self.recharge_amount
        return self.oop_total

    @api.depends('oop_total', 'service_type_id.commission_rate')
    def _compute_fee_amounts(self):
        for file in self:
            file.commission_amount = file.currency_id.round(
                file.oop_total * (file.service_type_id.commission_rate or 0.0) / 100.0)

    @api.depends('documents_complete', 'waiver_state')
    @api.depends('invoice_id.amount_total', 'advance_had_amount',
                 'advance_had_vat_amount', 'advance_other_amount')
    def _compute_invoice_balance_due(self):
        """What the client still owes once their advances come off."""
        for file in self:
            total = file.invoice_id.amount_total if file.invoice_id else 0.0
            file.invoice_balance_due = total - (
                file.advance_had_amount + file.advance_had_vat_amount
                + file.advance_other_amount)

    def _compute_can_start(self):
        for file in self:
            file.can_start = file.documents_complete or file.waiver_state == 'approved'

    # =====================================================================
    # Onchange
    # =====================================================================
    @api.onchange('service_type_id')
    def _onchange_service_type_id(self):
        """Populate the checklist as soon as the service type is chosen.

        Guarded so that changing the service type on a live file never
        silently discards a document already ticked as received — in that
        case the user presses "Reload Checklist" instead.
        """
        if not self.service_type_id:
            return
        if self.document_ids.filtered('received'):
            return {'warning': {
                'title': self.env._("Checklist not regenerated"),
                'message': self.env._(
                    "Some documents are already marked as received. Use the "
                    "Reload Checklist button to merge the new service type's "
                    "requirements without losing them."
                ),
            }}
        commands = [fields.Command.clear()]
        for template in self.service_type_id.document_ids:
            commands.append(fields.Command.create({
                'document_type_id': template.document_type_id.id,
                'is_mandatory': template.is_mandatory,
                'sequence': template.sequence,
            }))
        self.document_ids = commands

    # =====================================================================
    # CRUD
    # =====================================================================
    @api.model
    def _next_reference(self, kind, service_type, company):
        """Structured references per service type, yearly:
        files:   2026IM0009  = %(year)s + type code + 4-digit sequence
        billing: EL26IM0001  = EL + %(y)s + type code + 4-digit sequence
        The sequence per (kind, type, company) is created on first use and
        resets each year; ir.sequence guarantees no duplicates."""
        return self._get_reference_sequence(kind, service_type, company).next_by_id()

    @api.model
    def _get_reference_sequence(self, kind, service_type, company):
        """The ir.sequence behind a (kind, service type, company) reference,
        created on first use. Exposed so the legacy import can advance it
        past the numbers already taken in the old system."""
        code = (service_type.code or 'XX').upper()
        seq_code = 'logistics.%s.%s' % (kind, code)
        Seq = self.env['ir.sequence'].sudo()
        seq = Seq.search([('code', '=', seq_code),
                          ('company_id', 'in', [company.id, False])], limit=1)
        if not seq:
            prefix = ('EL%%(y)s%s' % code) if kind == 'billing' else ('%%(year)s%s' % code)
            seq = Seq.create({
                'name': "Clearance %s %s" % (kind, code),
                'code': seq_code,
                'prefix': prefix,
                'padding': 4,
                'company_id': company.id,
                'use_date_range': True,
            })
        return seq

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', "New") == "New" and vals.get('service_type_id'):
                company = self.env['res.company'].browse(
                    vals.get('company_id') or self.env.company.id)
                service_type = self.env['logistics.service.type'].browse(
                    vals['service_type_id'])
                vals['name'] = self._next_reference('file', service_type, company)
        files = super().create(vals_list)
        skip_checklist = self.env.context.get('skip_checklist')
        for file in files:
            if not file.document_ids and file.service_type_id and not skip_checklist:
                file._build_checklist()
            if not file.analytic_account_id:
                file._create_analytic_account()
        return files

    def unlink(self):
        for file in self:
            if file.state not in ('draft', 'cancel'):
                raise UserError(self.env._(
                    "File %s cannot be deleted once work has started. "
                    "Cancel it instead.", file.name,
                ))
        return super().unlink()

    # =====================================================================
    # Helpers
    # =====================================================================
    def _create_analytic_account(self):
        """One analytic account per file, under the Clearance Files plan."""
        self.ensure_one()
        plan = self.env.ref(
            'elite_clearance.analytic_plan_clearance', raise_if_not_found=False,
        )
        if not plan:
            return
        # The name IS the label: the file number once, then the client's
        # three-letter slug, so every tag in the analytic distribution reads
        # the same width - 2026AI0072 - CTC. account.analytic.account's
        # display_name is overridden for this plan to use it verbatim
        # instead of Odoo's "[code] name - full client name".
        slug = self.partner_id._clearance_ensure_slug()
        label = "%s - %s" % (self.name, slug) if slug else self.name
        # sudo(): the analytic account is a technical record the system owns,
        # not something the ops agent is choosing to create. Without this, a
        # clearance user without the Analytic Accounting group cannot open a
        # file at all.
        self.analytic_account_id = self.env['account.analytic.account'].sudo().create({
            'name': label,
            'code': self.name,
            'plan_id': plan.id,
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
        })

    def _build_checklist(self):
        """(Re)generate checklist lines from the service type template.

        Lines already ticked as received are preserved.
        """
        DocLine = self.env['logistics.file.document']
        for file in self:
            existing = {d.document_type_id.id: d for d in file.document_ids}
            keep = DocLine.browse()
            new_vals = []
            for template in file.service_type_id.document_ids:
                line = existing.get(template.document_type_id.id)
                if line:
                    line.is_mandatory = template.is_mandatory
                    keep |= line
                else:
                    new_vals.append({
                        'file_id': file.id,
                        'document_type_id': template.document_type_id.id,
                        'is_mandatory': template.is_mandatory,
                        'sequence': template.sequence,
                    })
            # Drop lines no longer in the template, unless already received.
            stale = file.document_ids - keep
            stale.filtered(lambda d: not d.received).unlink()
            if new_vals:
                DocLine.create(new_vals)

    def _check_manager(self):
        for file in self:
            file.company_id._clearance_check_approver('waiver')

    def _check_advances_billable(self):
        """Only engaged disbursements are billable.

        Anything still on 421101 is a staff debt with no supporting document
        behind it. Billing it would recharge the client for money we cannot
        evidence, so the file stops here unless an Operations Manager signs
        for it in writing.
        """
        self.ensure_one()
        if not self.unjustified_advance_total:
            return
        if self.advance_waiver_state == 'approved':
            return
        holders = self.expense_ids.filtered(
            lambda e: e.payment_mode == 'advance' and e.state == 'settled'
        ).mapped('employee_id.name')
        raise UserError(self.env._(
            "%(name)s carries %(amount)s advanced to staff (%(who)s) that is "
            "still unjustified on 421101. Justify it with the supporting "
            "documents, or obtain an Operations Manager's waiver.",
            name=self.name, amount=self.unjustified_advance_total,
            who=", ".join(sorted(set(holders))) or "-"))

    # =====================================================================
    # Actions
    # =====================================================================
    def action_reload_checklist(self):
        self._build_checklist()
        return True

    def action_request_waiver(self):
        for file in self:
            if file.documents_complete:
                raise UserError(self.env._(
                    "File %s already has complete documentation — no waiver "
                    "is needed.", file.name,
                ))
            if not file.waiver_reason:
                raise UserError(self.env._(
                    "Give a justification before requesting a waiver on %s.",
                    file.name,
                ))
            file.write({
                'waiver_state': 'requested',
                'waiver_requested_date': fields.Datetime.now(),
                'waiver_requested_by_id': self.env.user.id,
            })
            file.message_post(body=self.env._(
                "Documentation waiver requested: %s", file.waiver_reason,
            ))
        return True

    def action_approve_waiver(self):
        self._check_manager()
        for file in self:
            if file.waiver_state != 'requested':
                raise UserError(self.env._(
                    "No waiver is awaiting approval on %s.", file.name,
                ))
            file.write({
                'waiver_state': 'approved',
                'waiver_approved_by_id': self.env.user.id,
                'waiver_date': fields.Datetime.now(),
            })
            file.message_post(body=self.env._("Documentation waiver approved."))
        return True

    def action_refuse_waiver(self):
        self._check_manager()
        for file in self:
            if file.waiver_state != 'requested':
                raise UserError(self.env._(
                    "No waiver is awaiting approval on %s.", file.name,
                ))
            file.write({
                'waiver_state': 'refused',
                'waiver_approved_by_id': self.env.user.id,
                'waiver_date': fields.Datetime.now(),
            })
            file.message_post(body=self.env._("Documentation waiver refused."))
        return True

    def action_request_advance_waiver(self):
        for file in self:
            if not file.unjustified_advance_total:
                raise UserError(self.env._(
                    "%s has no unjustified staff advance — nothing to waive.",
                    file.name))
            if not file.advance_waiver_reason:
                raise UserError(self.env._(
                    "Explain why %s should be billed with an unsupported "
                    "staff advance, and how the advance will be recovered.",
                    file.name))
            file.write({'advance_waiver_state': 'requested',
                        'advance_waiver_requested_date':
                            fields.Datetime.now(),
                        'advance_waiver_requested_by_id': self.env.user.id})
            file.message_post(body=self.env._(
                "Waiver requested for %(amount)s of unjustified staff "
                "advances: %(reason)s",
                amount=file.unjustified_advance_total,
                reason=file.advance_waiver_reason))
        return True

    def action_approve_advance_waiver(self):
        for file in self:
            file.company_id._clearance_check_approver('advance_waiver')
            if file.advance_waiver_state != 'requested':
                raise UserError(self.env._(
                    "No unjustified-advance waiver is awaiting approval on "
                    "%s.", file.name))
            file.write({'advance_waiver_state': 'approved',
                        'advance_waiver_approved_by_id': self.env.user.id,
                        'advance_waiver_date': fields.Datetime.now()})
            # Spelled out because it is the point of the whole control: the
            # waiver releases the FILE, never the money.
            file.message_post(body=self.env._(
                "Unjustified-advance waiver approved. %(amount)s stays on "
                "421101 against the holder and is NOT recharged to the "
                "client; it remains recoverable from the staff member.",
                amount=file.unjustified_advance_total))
        return True

    def action_refuse_advance_waiver(self):
        for file in self:
            file.company_id._clearance_check_approver('advance_waiver')
            if file.advance_waiver_state != 'requested':
                raise UserError(self.env._(
                    "No unjustified-advance waiver is awaiting approval on "
                    "%s.", file.name))
            file.write({'advance_waiver_state': 'refused',
                        'advance_waiver_approved_by_id': self.env.user.id,
                        'advance_waiver_date': fields.Datetime.now()})
            file.message_post(body=self.env._(
                "Unjustified-advance waiver refused: the advance must be "
                "justified with supporting documents before billing."))
        return True

    # --- reopening an imported file -------------------------------------
    def action_request_reopen_imported(self):
        """The billing agent asks for an imported file to be worked again."""
        for file in self:
            file.company_id._clearance_check_approver('billing')
            if file.state != 'imported':
                raise UserError(self.env._(
                    "%s is not an imported file.", file.name))
            if not file.reopen_request_reason:
                raise UserError(self.env._(
                    "Say why %s should be reopened before requesting it.",
                    file.name))
            file.write({'reopen_request_state': 'requested',
                        'reopen_requested_by_id': self.env.user.id})
            file.message_post(body=self.env._(
                "Reopening requested: %s", file.reopen_request_reason))
        return True

    def action_approve_reopen_imported(self):
        """The Operations Manager, after review, releases it into the workflow."""
        for file in self:
            file.company_id._clearance_check_approver('reopen_imported')
            if file.reopen_request_state != 'requested':
                raise UserError(self.env._(
                    "No reopening request is awaiting approval on %s.", file.name))
            file.write({'reopen_request_state': 'approved',
                        'reopen_approved_by_id': self.env.user.id,
                        'reopen_request_date': fields.Datetime.now(),
                        'state': 'in_progress',
                        'date_closed': False})
            file.message_post(body=self.env._(
                "Imported file reopened by %s: it is now in progress and "
                "follows the normal workflow.", self.env.user.name))
        return True

    def action_refuse_reopen_imported(self):
        for file in self:
            file.company_id._clearance_check_approver('reopen_imported')
            if file.reopen_request_state != 'requested':
                raise UserError(self.env._(
                    "No reopening request is awaiting approval on %s.", file.name))
            file.write({'reopen_request_state': 'refused',
                        'reopen_approved_by_id': self.env.user.id,
                        'reopen_request_date': fields.Datetime.now()})
            file.message_post(body=self.env._(
                "Reopening refused: the file stays an imported record."))
        return True

    @api.constrains('customs_regime', 'state')
    def _check_customs_regime(self):
        """Mandatory to open a file and to work it.

        Imported files are exempt: they are Teese history, and inventing a
        regime for them would be worse than leaving it blank.
        """
        for file in self:
            if (file.legacy_id or file.state == 'imported'
                    or self.env.context.get('legacy_import')):
                continue        # Teese history, in whatever state
            if not file.customs_regime:
                raise ValidationError(self.env._(
                    "Choose the customs regime for %s (IM4, IM5, IM7 or "
                    "IM8) before saving it.", file.name or "the file"))

    def action_start_work(self):
        for file in self:
            if file.state != 'draft':
                raise UserError(self.env._(
                    "File %s is not in draft.", file.name,
                ))
            if not file.customs_regime:
                raise UserError(self.env._(
                    "Work cannot start on %s until its customs regime is "
                    "chosen.", file.name))
            if not file.can_start:
                raise UserError(self.env._(
                    "Work cannot start on %(name)s: %(count)s mandatory "
                    "document(s) are still missing and no waiver has been "
                    "approved.",
                    name=file.name, count=file.missing_mandatory_count,
                ))
            file.write({'state': 'in_progress',
                        'date_started': fields.Datetime.now()})
        return True

    def action_close_operations(self):
        """Operations are finished: no further expenses can be captured.

        Two gates, in order: an Operations Manager is closing it, and every
        expense is final (an unjustified staff advance being the one
        waivable exception).

        The customs fee used to be a third gate here. It is a BILLING
        parameter and now lives in the billing screen, where the billing
        agent sets it - so Operations no longer has to key a figure it does
        not own in order to hand the file on.
        """
        for file in self:
            # Closing is the Operations Manager's decision, not the agent's.
            file.company_id._clearance_check_approver('ops_close')
            if file.state != 'in_progress':
                raise UserError(self.env._(
                    "Only a file in progress can be closed for operations "
                    "(%s).", file.name))
            pending = file.expense_ids.filtered(
                lambda e: not e.is_final
                and not (e.payment_mode == 'advance' and e.state == 'settled'))
            if pending:
                raise UserError(self.env._(
                    "%(name)s still has %(count)s expense(s) not settled or "
                    "justified: %(refs)s.",
                    name=file.name, count=len(pending),
                    refs=", ".join(pending.mapped('name'))))
            # A settled-but-unjustified advance is handled separately: it is
            # waivable, where a half-processed expense is simply unfinished.
            file._check_advances_billable()
            file.write({'state': 'ops_closed',
                        'date_ops_closed': fields.Datetime.now()})
        return True

    # --- recharge adjustment --------------------------------------------
    def _check_recharge_documented(self):
        """Below cost the company absorbs the difference, so the file has
        to say why, in writing.

        A supporting document is welcome and is NOT required: owner's
        decision 05/09/2026. The explanation is the control; demanding an
        attachment as well only taught people to upload anything.
        """
        self.ensure_one()
        if self.recharge_variance >= 0:
            return
        if not self.recharge_reason:
            raise UserError(self.env._(
                "Recharging %(amount)s BELOW what was disbursed has to be "
                "explained in writing before anyone can approve it (%(file)s).",
                amount=abs(self.recharge_variance), file=self.name))

    def action_approve_recharge_ops(self):
        """Operations signs every adjustment. Below cost it is not enough."""
        for file in self:
            file.company_id._clearance_check_approver('recharge_ops')
            if file.recharge_state != 'requested':
                raise UserError(self.env._(
                    "No recharge adjustment is awaiting Operations on %s.",
                    file.name))
            file._check_recharge_documented()
            below = file.recharge_variance < 0
            file.write({
                'recharge_state': 'ops_approved' if below else 'approved',
                'recharge_ops_approved_by_id': self.env.user.id,
                'recharge_approved_date': fields.Datetime.now(),
            })
            file.message_post(body=self.env._(
                "Recharge adjustment approved by Operations.%s",
                self.env._(" It is below cost, so the General Manager must "
                           "approve it as well.") if below else ""))
        return True

    def action_approve_recharge_gm(self):
        """Only a below-cost recharge reaches here: the company is absorbing
        the difference, so the General Manager signs it too."""
        for file in self:
            file.company_id._clearance_check_approver('recharge_gm')
            if file.recharge_state != 'ops_approved':
                raise UserError(self.env._(
                    "No below-cost recharge is awaiting the General Manager "
                    "on %s.", file.name))
            file._check_recharge_documented()
            file.write({
                'recharge_state': 'approved',
                'recharge_gm_approved_by_id': self.env.user.id,
                'recharge_approved_date': fields.Datetime.now(),
            })
            file.message_post(body=self.env._(
                "Below-cost recharge approved by the General Manager: "
                "%(amount)s against a cost of %(cost)s.",
                amount=file.recharge_amount, cost=file.oop_total))
        return True

    def action_refuse_recharge(self):
        for file in self:
            file.company_id._clearance_check_approver('recharge_ops')
            if file.recharge_state not in ('requested', 'ops_approved'):
                raise UserError(self.env._(
                    "No recharge adjustment is awaiting approval on %s.",
                    file.name))
            file.write({'recharge_state': 'refused'})
            file.message_post(body=self.env._(
                "Recharge adjustment refused: the invoice bills at cost."))
        return True

    # =====================================================================
    # Billing
    # =====================================================================
    def _billable_expenses(self):
        """The disbursements this file may recharge.

        Engaged means paid direct, or advanced and since justified. Legacy
        rows were billed in the old system and never appear here.
        """
        self.ensure_one()
        return self.expense_ids.filtered(
            lambda e: not e.is_legacy and (
                e.state == 'justified'
                or (e.state == 'settled' and e.payment_mode != 'advance')))

    def _billing_debours_lines(self):
        """What the billing screen proposes for the disbursement section."""
        self.ensure_one()
        return [
            {'name': "%s — %s" % (expense.category_id.name, expense.description),
             'amount': expense.amount}
            for expense in self._billable_expenses()
        ]

    def _billing_service_lines(self):
        """What it proposes for the service section: the commission on
        disbursements, and the customs fee keyed from the declaration."""
        self.ensure_one()
        fee = self.company_id.clearance_fee_account_id
        services = []
        if self.commission_amount:
            services.append({
                'name': self.env._(
                    "Commission sur débours (%(rate).2f%%)",
                    rate=self.commission_rate),
                'amount': self.commission_amount,
                'account_id': (
                    self.company_id.clearance_commission_account_id or fee).id,
            })
        if self.customs_fee_amount:
            services.append({
                'name': self.env._(
                    "Honoraires Agréés en Douane (déclaration %s)",
                    self.customs_declaration_ref or "-"),
                'amount': self.customs_fee_amount,
                'account_id': (
                    self.company_id.clearance_service_fee_account_id or fee).id,
            })
        return services

    def action_open_billing(self):
        """The Billing button on a file that is OK for billing."""
        self.ensure_one()
        self.company_id._clearance_check_approver('billing')
        if self.state != 'ops_closed':
            raise UserError(self.env._(
                "%s is not OK for billing yet.", self.name))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Billing — %s", self.name),
            'res_model': 'logistics.billing.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id, 'default_file_id': self.id},
        }

    def _create_client_invoice(self, debours, services):
        """Build the client invoice from explicit lines.

        `debours` are recharged AT COST so the out-of-pocket account clears
        in full; anything the client is charged above or below that is one
        further line in its own P&L account. `services` are the fee lines,
        which unlike disbursements keep their default taxes.
        """
        self.ensure_one()
        self.company_id._clearance_check_approver('billing')
        if self.state != 'ops_closed':
            raise UserError(self.env._(
                "Close %s for operations before billing it.", self.name))
        if self.invoice_id and self.invoice_id.state != 'cancel' \
                and not self.invoice_id.is_legacy:
            raise UserError(self.env._(
                "%(file)s already has invoice %(inv)s.",
                file=self.name, inv=self.invoice_id.name or "in draft"))
        if self.recharge_state in ('requested', 'ops_approved'):
            raise UserError(self.env._(
                "The recharge adjustment on %s is still awaiting approval.",
                self.name))
        # Re-checked here and not only at ops-close: a file can be reopened,
        # expenses added, and closed again through the wizard.
        self._check_advances_billable()
        oop_account = self.company_id.clearance_oop_account_id
        fee_account = self.company_id.clearance_fee_account_id
        if not oop_account or not fee_account:
            raise UserError(self.env._(
                "Configure the Engaged Disbursements (47xx) and Fee Income "
                "accounts under Clearance → Configuration → Settings first."))
        journal = self.company_id.clearance_sale_journal_id
        if not journal:
            journal = self.env['account.journal'].search(
                [('type', '=', 'sale'), ('company_id', '=', self.company_id.id)],
                limit=1)
        if not journal:
            raise UserError(self.env._(
                "Company %s has no sales journal to invoice from.",
                self.company_id.name))
        analytic = ({str(self.analytic_account_id.id): 100}
                    if self.analytic_account_id else False)

        lines = []
        if debours:
            lines.append(fields.Command.create({
                'display_type': 'line_section',
                'name': self.env._("Out-of-pocket expenses recharged at cost"),
            }))
        for line in debours:
            lines.append(fields.Command.create({
                'name': line['name'],
                'quantity': 1.0,
                'price_unit': line['amount'],
                'account_id': oop_account.id,
                # Disbursements are recharged at cost and carry no tax: they
                # are the client's own liability paid on their behalf. The
                # fee lines below deliberately keep the default taxes.
                'tax_ids': [fields.Command.clear()],
                'clearance_category': 'debours',
                'clearance_unit': line.get('unit') or "Par dossier",
                'analytic_distribution': analytic,
            }))

        # 47xx clears in full whatever the client is charged; the difference
        # is the company's own gain or loss and lands in its own account.
        adjustment = self._recharge_total() - self.oop_total
        if not self.currency_id.is_zero(adjustment):
            if adjustment < 0:
                variance_account = (
                    self.company_id.clearance_oop_undercharge_account_id)
                label = self.env._(
                    "Out of pocket expense undercharge (disbursed %(cost)s, "
                    "recharged %(charged)s)", cost=self.oop_total,
                    charged=self._recharge_total())
                missing = "Disbursement Undercharge"
            else:
                variance_account = (
                    self.company_id.clearance_oop_overcharge_account_id)
                label = self.env._(
                    "Out of pocket expense overcharge (disbursed %(cost)s, "
                    "recharged %(charged)s)", cost=self.oop_total,
                    charged=self._recharge_total())
                missing = "Disbursement Overcharge"
            if not variance_account:
                raise UserError(self.env._(
                    "Configure the %s account under Clearance → "
                    "Configuration → Settings before billing an adjusted "
                    "recharge.", missing))
            lines.append(fields.Command.create({
                'name': label,
                'quantity': 1.0,
                'price_unit': adjustment,
                'account_id': variance_account.id,
                'tax_ids': [fields.Command.clear()],
                'analytic_distribution': analytic,
            }))

        if services:
            lines.append(fields.Command.create({
                'display_type': 'line_section',
                'name': self.env._("Service fees"),
            }))
        # VAT applies to what the company sells - its commission and its
        # fees - and never to disbursements, which are the client's own
        # liability settled on their behalf. The tax is named in Settings
        # rather than inherited from whichever account a line lands on, so
        # the invoice does not change meaning when an account does.
        service_taxes = self.company_id.clearance_service_tax_ids
        for line in services:
            lines.append(fields.Command.create({
                'name': line['name'],
                'quantity': 1.0,
                'price_unit': line['amount'],
                'account_id': line.get('account_id') or fee_account.id,
                'tax_ids': [fields.Command.set(service_taxes.ids)],
                'clearance_category': 'prestation',
                'clearance_unit': line.get('unit') or "Par dossier",
                'analytic_distribution': analytic,
            }))

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': journal.id,
            'logistics_file_id': self.id,
            # The billing reference is imposed rather than taken from the
            # journal sequence: Elite Advisors numbers invoices per service
            # type (EL26IM0001).
            'name': self._next_reference('billing', self.service_type_id,
                                         self.company_id),
            'partner_id': self.partner_id.id,
            'invoice_origin': self.name,
            'ref': self.name,
            'invoice_line_ids': lines,
        })
        self.invoice_id = invoice
        self.date_billed = fields.Datetime.now()
        self.message_post(body=self.env._(
            "Draft invoice created: disbursements %(oop)s recharged at "
            "%(charged)s, services %(fees)s.",
            oop=self.oop_total, charged=self._recharge_total(),
            fees=sum(line['amount'] for line in services)))
        if self.unjustified_advance_total:
            self.message_post(body=self.env._(
                "Billed under an approved waiver: %(amount)s of staff "
                "advances was NOT invoiced and stays on 421101 against the "
                "holder, to recover separately.",
                amount=self.unjustified_advance_total))
        return invoice

    def action_preview_invoice(self):
        """See the document before the client does."""
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(self.env._(
                "%s has not been billed yet, so there is nothing to "
                "preview.", self.name))
        # config=False deliberately. With it, an admin whose company has
        # no external_report_layout_id gets Odoo's "Configure Document
        # Layout" wizard INSTEAD of the invoice - and this template does
        # not use web.external_layout at all, so that layout has no say in
        # how the page looks. Pressing Preview must show the document.
        return self.env.ref(
            'elite_clearance.action_report_clearance_invoice'
        ).report_action(self.invoice_id, config=False)

    def action_create_invoice(self):
        """Bill at the proposed figures, without opening the screen."""
        self.ensure_one()
        invoice = self._create_client_invoice(
            self._billing_debours_lines(), self._billing_service_lines())
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
        }

    def action_mark_complete(self):
        """Final close: only once the client invoice is posted."""
        for file in self:
            file.company_id._clearance_check_approver('billing')
            if file.state != 'ops_closed':
                raise UserError(self.env._(
                    "%s must be closed for operations first.", file.name))
            if not file.invoice_id or file.invoice_id.state != 'posted':
                raise UserError(self.env._(
                    "Post the client invoice on %s before marking it "
                    "complete.", file.name))
            file.write({'state': 'done',
                        'date_closed': fields.Date.context_today(file)})
        return True

    def action_cancel(self):
        for file in self:
            if file.state == 'imported':
                raise UserError(self.env._(
                    "%s is an imported record of work done in the legacy "
                    "system. It is history and cannot be cancelled.",
                    file.name))
            if file.state == 'draft':
                # An empty draft is the author's own to throw away.
                file.state = 'cancel'
                continue
            file.company_id._clearance_check_approver('waiver')
            if file.invoice_id and file.invoice_id.state == 'posted':
                raise UserError(self.env._(
                    "%(file)s carries posted invoice %(inv)s. Credit-note the "
                    "invoice from Accounting before cancelling the file.",
                    file=file.name, inv=file.invoice_id.name))
            unfinished = file.expense_ids.filtered(
                lambda e: e.state not in ('draft', 'cancel'))
            if unfinished:
                raise UserError(self.env._(
                    "%(name)s still carries %(count)s live expense(s): "
                    "%(refs)s. Refuse or settle and reverse them first.",
                    name=file.name, count=len(unfinished),
                    refs=", ".join(unfinished.mapped('name'))))
            file.state = 'cancel'
            file.message_post(body=self.env._(
                "File cancelled by %s.", self.env.user.name))
        return True

    def action_reset_to_draft(self):
        for file in self:
            if file.state != 'cancel':
                raise UserError(self.env._(
                    "Only a cancelled file can be reset to draft. A closed "
                    "file is reopened through the approval flow (%s).",
                    file.name))
        self.write({'state': 'draft', 'date_closed': False})
        return True


class LogisticsFileDocument(models.Model):
    """One checklist line on a clearance file."""

    _name = 'logistics.file.document'
    _description = "Clearance File Document"
    _order = 'sequence, id'
    _rec_name = 'document_type_id'

    file_id = fields.Many2one(
        'logistics.file', required=True, ondelete='cascade', index=True,
    )
    document_type_id = fields.Many2one(
        'logistics.document.type', required=True, ondelete='restrict',
    )
    sequence = fields.Integer(default=10)
    is_mandatory = fields.Boolean(string="Mandatory", default=True)
    received = fields.Boolean(string="Received")
    date_received = fields.Datetime(string="Received On")
    reference = fields.Char(string="Document Ref.")
    note = fields.Char()
    company_id = fields.Many2one(related='file_id.company_id', store=True, index=True)

    _document_per_file_uniq = models.Constraint(
        'UNIQUE(file_id, document_type_id)',
        "This document is already on the file's checklist.",
    )

    @api.onchange('received')
    def _onchange_received(self):
        for line in self:
            if line.received and not line.date_received:
                line.date_received = fields.Datetime.now()
            elif not line.received:
                line.date_received = False

    @api.constrains('received', 'date_received')
    def _check_date_received(self):
        now = fields.Datetime.now()
        for line in self:
            if line.date_received and line.date_received > now:
                raise ValidationError(self.env._(
                    "A document cannot be received in the future (%s).",
                    line.document_type_id.name,
                ))

    # The onchange above only fires while a person edits the form. These two
    # hooks make the stamp reliable on EVERY path — imports, automations, the
    # API, and the list toggle alike.
    # self.env.cr.now() is the TRANSACTION time: constant for everything
    # saved together. Tick five documents and press Save once — all five
    # carry the identical timestamp, to the second.
    @api.model_create_multi
    def create(self, vals_list):
        now = self.env.cr.now().replace(microsecond=0)
        for vals in vals_list:
            if vals.get('received') and not vals.get('date_received'):
                vals['date_received'] = now
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('received') and 'date_received' not in vals:
            # Stamp only lines that have no timestamp yet; never overwrite a
            # date someone set deliberately (or via the wizard).
            now = self.env.cr.now().replace(microsecond=0)
            undated = self.filtered(lambda l: not l.date_received)
            dated = self - undated
            res = True
            if undated:
                res = super(LogisticsFileDocument, undated).write(
                    dict(vals, date_received=now))
            if dated:
                res = super(LogisticsFileDocument, dated).write(vals) and res
            return res
        if 'received' in vals and not vals['received'] and 'date_received' not in vals:
            vals = dict(vals, date_received=False)
        return super().write(vals)
