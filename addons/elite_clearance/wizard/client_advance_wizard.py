from odoo import api, fields, models
from odoo.exceptions import UserError


class LogisticsClientAdvanceWizard(models.TransientModel):
    """Record money the client has put up against a clearance file.

    The owner's rule of 15/09/2026: an advance is a real receipt, against
    the client's own account, carrying the file's analytic tag like
    everything else the file touches - not a figure typed on the invoice.
    It is posted straight away and then shows on the invoice, so the
    client reads what is actually left to pay.
    """

    _name = 'logistics.client.advance.wizard'
    _description = "Record a Client Advance"

    file_id = fields.Many2one(
        'logistics.file', string="Clearance File", required=True, readonly=True)
    partner_id = fields.Many2one(related='file_id.partner_id', string="Client")
    currency_id = fields.Many2one(related='file_id.currency_id')
    amount = fields.Monetary(
        string="Amount Received", currency_field='currency_id', required=True)
    date = fields.Date(
        string="Received On", required=True,
        default=fields.Date.context_today)
    journal_id = fields.Many2one(
        'account.journal', string="Received Into", required=True,
        domain="[('type', 'in', ('bank', 'cash'))]",
        help="The till or the account the money went into.")
    memo = fields.Char(
        string="Reference",
        help="What the client called it - a transfer reference, a receipt "
             "number. Left empty, the file's own reference is used.")
    already_received = fields.Monetary(
        related='file_id.client_advance_total', currency_field='currency_id',
        string="Already received on this file")

    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        file = self.env['logistics.file'].browse(
            vals.get('file_id') or self.env.context.get('active_id'))
        if file:
            vals['file_id'] = file.id
            journal = file.company_id.clearance_advance_receipt_journal_id
            if journal:
                vals['journal_id'] = journal.id
        return vals

    def action_record_advance(self):
        self.ensure_one()
        file = self.file_id
        if self.currency_id.compare_amounts(self.amount, 0.0) <= 0:
            raise UserError(self.env._(
                "An advance of nothing is not an advance. Key what the "
                "client actually paid."))
        if not file.partner_id:
            raise UserError(self.env._(
                "%s has no client, so there is nobody to credit.",
                file.name))
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': file.partner_id.id,
            'amount': self.amount,
            'date': self.date,
            'journal_id': self.journal_id.id,
            'memo': self.memo or file.name,
        })
        # Odoo 19 does not make the journal entry until the payment is
        # posted - account.payment.move_id is empty before that, and
        # writing the file on it beforehand writes on nothing at all. So
        # post first, then name the file and tag the lines by hand, since
        # _post has already been and gone.
        payment.action_post()
        move = payment.move_id
        if not move:
            raise UserError(self.env._(
                "%s made no journal entry, which means it has no "
                "outstanding receipts account configured. Set one on the "
                "journal, or on the payment method, before recording "
                "advances into it.", self.journal_id.display_name))
        move.logistics_file_id = file.id
        move._clearance_stamp_analytic()
        file.message_post(body=self.env._(
            "Client advance of %(amount)s received on %(date)s into "
            "%(journal)s (%(payment)s). It comes off the invoice.",
            amount=self.amount, date=self.date,
            journal=self.journal_id.name, payment=payment.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'res_id': payment.id,
            'view_mode': 'form',
        }
