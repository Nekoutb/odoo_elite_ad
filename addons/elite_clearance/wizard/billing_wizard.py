from odoo import api, fields, models
from odoo.exceptions import UserError

# The two service lines Elimelec bills on nearly every file. They are
# proposed, not imposed: the biller edits them, deletes them, or adds
# whatever else the job carried.
SERVICE_HAD = "Honoraires Agréés en Douane"
SERVICE_COMMISSION = "Commission sur débours"


class LogisticsBillingWizard(models.TransientModel):
    """The billing screen for a file that is OK for billing.

    Shows what was disbursed and what will be charged for it, side by side,
    and lets the biller change the recharge line by line. Changing it is not
    something the biller can simply do: any difference from cost has to be
    approved before an invoice exists, so when there is one the only way
    forward is Submit for Review.
    """

    _name = 'logistics.billing.wizard'
    _description = "Bill a Clearance File"

    file_id = fields.Many2one(
        'logistics.file', string="Clearance File", required=True, readonly=True)
    partner_id = fields.Many2one(related='file_id.partner_id', string="Client")
    currency_id = fields.Many2one(related='file_id.currency_id')
    debours_line_ids = fields.One2many(
        'logistics.billing.wizard.debours', 'wizard_id',
        string="Out-of-pocket expenses")
    service_line_ids = fields.One2many(
        'logistics.billing.wizard.service', 'wizard_id',
        string="Additional services")

    # The two structured parameters. They are only settable here, on a file
    # that is already OK for billing: nothing about what the client is
    # charged is adjustable while operations are still running.
    commission_rate = fields.Float(
        string="Commission Rate (%)", digits=(6, 3),
        help="Charged on what the disbursements are recharged at. Proposed "
             "from the service type; the billing agent may change it for "
             "this file.")
    commission_amount = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        string="Commission sur débours")
    customs_fee_amount = fields.Monetary(
        string="Honoraires Agréés en Douane", currency_field='currency_id',
        help="Read from the customs declaration. Keyed here, at billing, "
             "by the agent who bills it.")

    debours_engaged_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        string="Disbursed")
    debours_recharged_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        string="Recharged")
    debours_variance = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        string="Variance")
    service_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        string="Services")
    service_tax_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        string="VAT on services",
        help="Configured in Settings, and charged on the service lines "
             "only. Disbursements are recharged without VAT.")
    invoice_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        string="Invoice Total")
    needs_review = fields.Boolean(
        compute='_compute_totals',
        help="True while the recharge differs from what was disbursed and "
             "that difference has not been approved. No invoice can be "
             "raised until it is.")
    advance_had_amount = fields.Monetary(
        string="Advance HAD/DAU", currency_field='currency_id',
        help="Already advanced by the client against the customs fee. "
             "Deducted on the face of the invoice, not from the total due "
             "in the accounts.")
    advance_had_vat_amount = fields.Monetary(
        string="Advance VAT on HAD/DAU", currency_field='currency_id')
    advance_other_amount = fields.Monetary(
        string="Other Advances", currency_field='currency_id')

    review_reason = fields.Text(
        string="Why the recharge differs from cost",
        help="Required before anyone can approve it. Below cost the company "
             "absorbs the difference, so this is the record of why.")

    # ------------------------------------------------------------------
    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        file = self.env['logistics.file'].browse(
            vals.get('file_id') or self.env.context.get('active_id'))
        if not file:
            return vals
        vals['file_id'] = file.id
        vals['review_reason'] = file.recharge_reason or False
        vals['debours_line_ids'] = [
            fields.Command.create({
                'expense_id': expense.id,
                'name': "%s — %s" % (expense.category_id.name, expense.description),
                'amount_engaged': expense.amount,
                'unit_label': expense.unit_label or "Par dossier",
                'amount_recharged': (
                    expense.recharge_amount or expense.amount),
            })
            for expense in file._billable_expenses()
        ]
        # The commission and the customs fee are parameters now, not rows:
        # the agent sets a rate and a figure and watches the total move.
        # The list below is for anything else the job carried.
        vals['commission_rate'] = (
            file.billing_commission_rate or file.commission_rate)
        vals['customs_fee_amount'] = file.customs_fee_amount
        vals['advance_had_amount'] = file.advance_had_amount
        vals['advance_had_vat_amount'] = file.advance_had_vat_amount
        vals['advance_other_amount'] = file.advance_other_amount
        vals['service_line_ids'] = []
        return vals

    def _service_lines_for_invoice(self):
        """What the invoice's service section will contain."""
        self.ensure_one()
        company = self.file_id.company_id
        fallback = company.clearance_fee_account_id
        services = []
        if not self.currency_id.is_zero(self.commission_amount):
            services.append({
                'name': self.env._("%(label)s (%(rate).2f%%)",
                                   label=SERVICE_COMMISSION,
                                   rate=self.commission_rate),
                'amount': self.commission_amount,
                'unit': "Par dossier",
                'account_id': (company.clearance_commission_account_id
                               or fallback).id,
            })
        if not self.currency_id.is_zero(self.customs_fee_amount):
            services.append({
                'name': self.env._(
                    "%(label)s (déclaration %(ref)s)", label=SERVICE_HAD,
                    ref=self.file_id.customs_declaration_ref or "-"),
                'amount': self.customs_fee_amount,
                'unit': "Par dossier",
                'account_id': (company.clearance_service_fee_account_id
                               or fallback).id,
            })
        for line in self.service_line_ids:
            if self.currency_id.is_zero(line.amount):
                continue
            services.append({
                'name': line.name,
                'amount': line.amount,
                'unit': line.unit_label or "Par dossier",
                'account_id': (line.account_id or fallback).id,
            })
        return services

    @api.depends('debours_line_ids.amount_engaged',
                 'debours_line_ids.amount_recharged',
                 'service_line_ids.amount', 'commission_rate',
                 'customs_fee_amount',
                 'file_id.recharge_state', 'file_id.recharge_amount')
    def _compute_totals(self):
        for wizard in self:
            engaged = sum(wizard.debours_line_ids.mapped('amount_engaged'))
            recharged = sum(wizard.debours_line_ids.mapped('amount_recharged'))
            wizard.debours_engaged_total = engaged
            wizard.debours_recharged_total = recharged
            wizard.debours_variance = recharged - engaged
            wizard.commission_amount = wizard.currency_id.round(
                recharged * wizard.commission_rate / 100.0
            ) if wizard.currency_id else 0.0
            wizard.service_total = (
                wizard.commission_amount + wizard.customs_fee_amount
                + sum(wizard.service_line_ids.mapped('amount')))
            # VAT rides on the services and never on the disbursements, so
            # the biller sees the same split the invoice will carry.
            taxes = wizard.file_id.company_id.clearance_service_tax_ids
            tax = 0.0
            if taxes and wizard.service_total:
                tax = sum(
                    step['amount'] for step in taxes.compute_all(
                        wizard.service_total,
                        currency=wizard.currency_id,
                    )['taxes'])
            wizard.service_tax_total = tax
            wizard.invoice_total = recharged + wizard.service_total + tax
            file = wizard.file_id
            settled = (
                file.recharge_state == 'approved'
                and not file.currency_id.compare_amounts(
                    file.recharge_amount, recharged))
            wizard.needs_review = bool(
                file.currency_id.compare_amounts(recharged, engaged)
                and not settled)

    # ------------------------------------------------------------------
    def _persist(self):
        """Record the biller's intent on the file and its expenses.

        Per-line figures are kept even though the invoice recharges at cost
        and books the difference separately: which disbursement was
        discounted, and by how much, is worth knowing later.
        """
        self.ensure_one()
        for line in self.debours_line_ids:
            if line.expense_id:
                line.expense_id.recharge_amount = line.amount_recharged
        recharged = self.debours_recharged_total
        at_cost = not self.file_id.currency_id.compare_amounts(
            recharged, self.debours_engaged_total)
        self.file_id.write({
            'recharge_amount': 0.0 if at_cost else recharged,
            'recharge_reason': self.review_reason or False,
            'billing_commission_rate': self.commission_rate,
            'customs_fee_amount': self.customs_fee_amount,
            'advance_had_amount': self.advance_had_amount,
            'advance_had_vat_amount': self.advance_had_vat_amount,
            'advance_other_amount': self.advance_other_amount,
        })

    def action_submit_for_review(self):
        self.ensure_one()
        if not self.needs_review:
            raise UserError(self.env._(
                "%s recharges exactly what was disbursed - there is nothing "
                "to review.", self.file_id.name))
        if not self.review_reason:
            raise UserError(self.env._(
                "Say why the recharge differs from what was disbursed before "
                "sending it for review."))
        self._persist()
        return {'type': 'ir.actions.act_window_close'}

    def action_create_invoice(self):
        self.ensure_one()
        if self.needs_review:
            raise UserError(self.env._(
                "The recharge on %s differs from what was disbursed and has "
                "not been approved. Send it for review first.",
                self.file_id.name))
        services = self._service_lines_for_invoice()
        if not self.debours_line_ids and not services:
            raise UserError(self.env._("There is nothing to bill on %s.",
                                       self.file_id.name))
        self._persist()
        invoice = self.file_id._create_client_invoice(
            [{'name': line.name, 'amount': line.amount_engaged,
              'unit': line.unit_label or "Par dossier"}
             for line in self.debours_line_ids],
            services,
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
        }


class LogisticsBillingWizardDebours(models.TransientModel):
    _name = 'logistics.billing.wizard.debours'
    _description = "Billing Wizard — Disbursement Line"
    _order = 'id'

    wizard_id = fields.Many2one(
        'logistics.billing.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    expense_id = fields.Many2one('logistics.expense', readonly=True)
    name = fields.Char(string="Description", required=True)
    unit_label = fields.Char(string="Unit", default="Par dossier")
    amount_engaged = fields.Monetary(
        string="Disbursed", readonly=True, currency_field='currency_id')
    amount_recharged = fields.Monetary(
        string="To Recharge", currency_field='currency_id',
        help="What the client is charged for this disbursement. Any "
             "difference from what was disbursed needs approving.")
    variance = fields.Monetary(
        compute='_compute_variance', currency_field='currency_id',
        string="Variance")

    @api.depends('amount_engaged', 'amount_recharged')
    def _compute_variance(self):
        for line in self:
            line.variance = line.amount_recharged - line.amount_engaged


class LogisticsBillingWizardService(models.TransientModel):
    _name = 'logistics.billing.wizard.service'
    _description = "Billing Wizard — Service Line"
    _order = 'id'

    wizard_id = fields.Many2one(
        'logistics.billing.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    unit_label = fields.Char(string="Unit", default="Par dossier")
    service_id = fields.Many2one(
        'logistics.billing.service', string="Billable Service",
        domain="[('state', '=', 'approved')]",
        help="Only services an Operations Manager has approved can be "
             "billed. Propose a new one from Billing > Billable Services.")
    name = fields.Char(string="Service", required=True)
    amount = fields.Monetary(string="Amount", currency_field='currency_id')
    account_id = fields.Many2one(
        'account.account', string="Income Account",
        domain="[('account_type', 'in', ('income', 'income_other'))]",
        help="Where this fee is credited. Left empty it falls back to the "
             "company's clearance fee income account.")

    @api.onchange('service_id')
    def _onchange_service_id(self):
        for line in self:
            if line.service_id:
                line.name = line.service_id.name
                line.amount = line.service_id.default_amount
                line.account_id = line.service_id.account_id
                line.unit_label = line.service_id.unit_label
