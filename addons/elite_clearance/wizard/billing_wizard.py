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
        'logistics.billing.wizard.service', 'wizard_id', string="Services")

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
    invoice_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        string="Invoice Total")
    needs_review = fields.Boolean(
        compute='_compute_totals',
        help="True while the recharge differs from what was disbursed and "
             "that difference has not been approved. No invoice can be "
             "raised until it is.")
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
                'amount_recharged': (
                    expense.recharge_amount or expense.amount),
            })
            for expense in file._billable_expenses()
        ]
        services = []
        if file.commission_amount:
            services.append({
                'name': SERVICE_COMMISSION,
                'amount': file.commission_amount,
                'account_id': (file.company_id.clearance_commission_account_id
                               or file.company_id.clearance_fee_account_id).id,
            })
        if file.customs_fee_amount:
            services.append({
                'name': SERVICE_HAD,
                'amount': file.customs_fee_amount,
                'account_id': (file.company_id.clearance_service_fee_account_id
                               or file.company_id.clearance_fee_account_id).id,
            })
        vals['service_line_ids'] = [
            fields.Command.create(service) for service in services]
        return vals

    @api.depends('debours_line_ids.amount_engaged',
                 'debours_line_ids.amount_recharged',
                 'service_line_ids.amount',
                 'file_id.recharge_state', 'file_id.recharge_amount')
    def _compute_totals(self):
        for wizard in self:
            engaged = sum(wizard.debours_line_ids.mapped('amount_engaged'))
            recharged = sum(wizard.debours_line_ids.mapped('amount_recharged'))
            wizard.debours_engaged_total = engaged
            wizard.debours_recharged_total = recharged
            wizard.debours_variance = recharged - engaged
            wizard.service_total = sum(wizard.service_line_ids.mapped('amount'))
            wizard.invoice_total = recharged + wizard.service_total
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
        if not self.debours_line_ids and not self.service_line_ids:
            raise UserError(self.env._("There is nothing to bill on %s.",
                                       self.file_id.name))
        self._persist()
        invoice = self.file_id._create_client_invoice(
            [{'name': line.name, 'amount': line.amount_engaged}
             for line in self.debours_line_ids],
            [{'name': line.name, 'amount': line.amount,
              'account_id': line.account_id.id}
             for line in self.service_line_ids if line.amount],
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
    name = fields.Char(string="Service", required=True)
    amount = fields.Monetary(string="Amount", currency_field='currency_id')
    account_id = fields.Many2one(
        'account.account', string="Income Account",
        domain="[('account_type', 'in', ('income', 'income_other'))]",
        help="Where this fee is credited. Left empty it falls back to the "
             "company's clearance fee income account.")
