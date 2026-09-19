from odoo import api, fields, models
from odoo.exceptions import UserError

OPEN_STATES = ('draft', 'in_progress', 'ops_closed')


class LogisticsPaymentAttributionWizard(models.TransientModel):
    """Put a customer receipt against one of that customer's open files.

    The owner's rule of 19/09/2026: money is recognised on the bank
    journal first and attributed afterwards. Once the payment names a
    customer, this shows every file of theirs that is still open - what
    it is, when it was opened, where it sits and what has already been
    advanced on it - and takes one. From then on the receipt carries that
    file's analytic account on every line, and the billing screen reads
    it back under Other Advances without anybody typing a figure.
    """

    _name = 'logistics.payment.attribution.wizard'
    _description = "Put a Receipt Against a Clearance File"

    payment_id = fields.Many2one(
        'account.payment', string="Receipt", required=True, readonly=True)
    partner_id = fields.Many2one(
        related='payment_id.partner_id', string="Customer")
    currency_id = fields.Many2one(related='payment_id.currency_id')
    amount = fields.Monetary(
        related='payment_id.amount', currency_field='currency_id',
        string="Amount Received")
    date = fields.Date(related='payment_id.date', string="Received On")
    journal_id = fields.Many2one(
        related='payment_id.journal_id', string="Received Into")
    current_file_id = fields.Many2one(
        related='payment_id.logistics_file_id', string="Currently against")

    candidate_ids = fields.Many2many(
        'logistics.file', compute='_compute_candidates',
        string="Open files for this customer")
    candidate_count = fields.Integer(compute='_compute_candidates')
    file_id = fields.Many2one(
        'logistics.file', string="Put it against", required=True,
        domain="[('id', 'in', candidate_ids)]")

    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        payment = self.env['account.payment'].browse(
            vals.get('payment_id') or self.env.context.get('active_id'))
        if payment:
            vals['payment_id'] = payment.id
        return vals

    @api.depends('payment_id')
    def _compute_candidates(self):
        for wizard in self:
            payment = wizard.payment_id
            files = self.env['logistics.file']
            if payment.partner_id:
                files = self.env['logistics.file'].search([
                    ('partner_id', '=', payment.partner_id.id),
                    ('state', 'in', OPEN_STATES),
                    ('company_id', '=', payment.company_id.id),
                ])
            wizard.candidate_ids = files
            wizard.candidate_count = len(files)

    # ------------------------------------------------------------------
    def action_attribute(self):
        self.ensure_one()
        payment = self.payment_id
        file = self.file_id
        if file.partner_id != payment.partner_id:
            raise UserError(self.env._(
                "%(file)s belongs to %(other)s, and this receipt came from "
                "%(client)s.",
                file=file.name, other=file.partner_id.display_name,
                client=payment.partner_id.display_name))
        move = payment.move_id
        if not move:
            raise UserError(self.env._(
                "%s has made no journal entry yet, so there is nothing to "
                "tag. Confirm the payment first.", payment.display_name))
        previous = move.logistics_file_id
        move.logistics_file_id = file.id
        # force: on a correction the lines already carry the OLD file's
        # account, and the ordinary stamp only fills lines that carry
        # none. The whole entry belongs to one file or to the other.
        move._clearance_stamp_analytic(force=bool(previous and previous != file))
        body = self.env._(
            "Client advance of %(amount)s received on %(date)s into "
            "%(journal)s (%(payment)s). It comes off this file's invoice.",
            amount=self.amount, date=self.date,
            journal=self.journal_id.display_name, payment=payment.name)
        file.message_post(body=body)
        if previous and previous != file:
            previous.message_post(body=self.env._(
                "%(payment)s was moved off this file and on to "
                "%(file)s.", payment=payment.name, file=file.name))
        payment.message_post(body=self.env._(
            "Put against clearance file %s.", file.name))
        return {'type': 'ir.actions.act_window_close'}
