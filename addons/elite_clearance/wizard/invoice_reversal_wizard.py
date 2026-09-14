from odoo import api, fields, models
from odoo.exceptions import UserError


class LogisticsInvoiceCreditWizard(models.TransientModel):
    """Credit part of a clearance invoice, line by line.

    The owner's rule of 13/09/2026: a credit note is not a button. The
    billing agent says why first, then picks the lines that are wrong;
    those lines and only those are reversed in the general ledger, and
    what they billed becomes billable again so the file can be invoiced
    afresh under the new instructions.
    """

    _name = 'logistics.invoice.credit.wizard'
    _description = "Credit a Clearance Invoice"

    invoice_id = fields.Many2one(
        'account.move', string="Invoice", required=True, readonly=True)
    file_id = fields.Many2one(
        related='invoice_id.logistics_file_id', string="Clearance File")
    partner_id = fields.Many2one(related='invoice_id.partner_id', string="Client")
    currency_id = fields.Many2one(related='invoice_id.currency_id')
    invoice_total = fields.Monetary(
        related='invoice_id.amount_total', currency_field='currency_id',
        string="Invoice Total")
    reason = fields.Text(
        string="Why this credit note is issued", required=True,
        help="It is printed nowhere, and it is the only record of why the "
             "client was billed one thing and then another. Say what was "
             "wrong, not that something was.")
    line_ids = fields.One2many(
        'logistics.invoice.credit.wizard.line', 'wizard_id',
        string="Lines to reverse")
    credit_total = fields.Monetary(
        compute='_compute_credit_total', currency_field='currency_id',
        string="Credited")
    credit_tax_total = fields.Monetary(
        compute='_compute_credit_total', currency_field='currency_id',
        string="VAT reversed")
    whole_invoice = fields.Boolean(
        compute='_compute_credit_total',
        help="Every line that still stands has been chosen, so this credit "
             "note reverses the invoice entirely.")

    # ------------------------------------------------------------------
    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        invoice = self.env['account.move'].browse(
            vals.get('invoice_id') or self.env.context.get('active_id'))
        if not invoice:
            return vals
        vals['invoice_id'] = invoice.id
        vals['line_ids'] = [
            fields.Command.create({
                'move_line_id': line.id,
                'name': line.name,
                'amount': line.price_subtotal,
                'tax_amount': line.price_total - line.price_subtotal,
                'already_credited': line.clearance_credited,
            })
            for line in invoice._clearance_creditable_lines()
        ]
        return vals

    @api.depends('line_ids.selected', 'line_ids.amount', 'line_ids.tax_amount')
    def _compute_credit_total(self):
        for wizard in self:
            chosen = wizard.line_ids.filtered('selected')
            wizard.credit_total = sum(chosen.mapped('amount'))
            wizard.credit_tax_total = sum(chosen.mapped('tax_amount'))
            standing = wizard.line_ids.filtered(
                lambda line: not line.already_credited)
            wizard.whole_invoice = bool(standing) and chosen == standing

    # ------------------------------------------------------------------
    def action_create_credit_note(self):
        self.ensure_one()
        invoice = self.invoice_id
        invoice.company_id._clearance_check_approver('billing')
        if not (self.reason or "").strip():
            raise UserError(self.env._(
                "Say why %s is being credited before any line is reversed.",
                invoice.name))
        if invoice.logistics_file_id:
            invoice.logistics_file_id._check_open_for_billing()
        chosen = self.line_ids.filtered('selected')
        if not chosen:
            raise UserError(self.env._(
                "Choose the lines to reverse on %s.", invoice.name))
        stale = chosen.filtered('already_credited')
        if stale:
            raise UserError(self.env._(
                "These lines have been credited already: %s.",
                ", ".join(stale.mapped('name'))))
        lines = chosen.mapped('move_line_id')
        credit = invoice._clearance_raise_credit_note(lines, self.reason)
        lines.clearance_credited = True
        invoice.message_post(body=self.env._(
            "Credit note %(credit)s raised over %(count)s line(s) of this "
            "invoice: %(reason)s",
            credit=credit.name, count=len(lines), reason=self.reason))
        file = invoice.logistics_file_id
        if file:
            file.message_post(body=self.env._(
                "%(count)s line(s) of %(inv)s credited by %(credit)s "
                "(%(user)s): %(reason)s%(gap)sWhat they billed is billable "
                "again.",
                count=len(lines), inv=invoice.name, credit=credit.name,
                user=self.env.user.name, reason=self.reason,
                gap=chr(10) * 2))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': credit.id,
            'view_mode': 'form',
        }


class LogisticsInvoiceCreditWizardLine(models.TransientModel):
    _name = 'logistics.invoice.credit.wizard.line'
    _description = "Credit a Clearance Invoice — Line"
    _order = 'id'

    wizard_id = fields.Many2one(
        'logistics.invoice.credit.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    move_line_id = fields.Many2one(
        'account.move.line', required=True, ondelete='cascade')
    name = fields.Char(string="Line", readonly=True)
    amount = fields.Monetary(
        string="Amount", currency_field='currency_id', readonly=True)
    tax_amount = fields.Monetary(
        string="VAT", currency_field='currency_id', readonly=True)
    already_credited = fields.Boolean(string="Already credited", readonly=True)
    selected = fields.Boolean(string="Reverse")


class LogisticsInvoiceCancelWizard(models.TransientModel):
    """Cancel a clearance invoice outright.

    A draft invoice is simply cancelled - it made no entry, so there is
    nothing to undo. A posted one is never unposted: the entry it made is
    the record of what the client was told, so cancelling it books that
    entry again with the signs the other way round (owner, 13/09/2026).
    """

    _name = 'logistics.invoice.cancel.wizard'
    _description = "Cancel a Clearance Invoice"

    invoice_id = fields.Many2one(
        'account.move', string="Invoice", required=True, readonly=True)
    file_id = fields.Many2one(
        related='invoice_id.logistics_file_id', string="Clearance File")
    currency_id = fields.Many2one(related='invoice_id.currency_id')
    invoice_state = fields.Selection(
        related='invoice_id.state', string="Invoice Status")
    invoice_total = fields.Monetary(
        related='invoice_id.amount_total', currency_field='currency_id',
        string="Invoice Total")
    reason = fields.Text(
        string="Why it is cancelled", required=True,
        help="Kept on the invoice and posted to the file. A cancelled "
             "invoice the client has seen is a question somebody will ask "
             "about later.")

    def action_cancel_invoice(self):
        self.ensure_one()
        invoice = self.invoice_id
        invoice.company_id._clearance_check_approver('billing')
        if not (self.reason or "").strip():
            raise UserError(self.env._(
                "Say why %s is being cancelled.", invoice.name))
        if not invoice._clearance_stands():
            raise UserError(self.env._(
                "%s has been cancelled already.", invoice.name))
        if invoice.logistics_file_id:
            invoice.logistics_file_id._check_open_for_billing()
        credit = self.env['account.move']
        if invoice.state == 'posted':
            credit = invoice._clearance_raise_credit_note(
                invoice._clearance_creditable_lines(standing_only=True),
                self.reason)
        else:
            invoice.button_cancel()
        invoice.write({
            'clearance_voided': True,
            'clearance_void_reason': self.reason,
            'clearance_voided_by_id': self.env.user.id,
            'clearance_void_date': fields.Datetime.now(),
        })
        invoice.message_post(body=self.env._(
            "Invoice cancelled by %(user)s: %(reason)s%(gap)s%(entry)s",
            user=self.env.user.name, reason=self.reason, gap=chr(10) * 2,
            entry=(self.env._(
                "The entry it made has been reversed by %s.", credit.name)
                if credit else self.env._(
                "It was still a draft, so it made no entry to reverse."))))
        file = invoice.logistics_file_id
        if file:
            file.message_post(body=self.env._(
                "%(inv)s cancelled by %(user)s: %(reason)s%(gap)sThe file "
                "is billable again.",
                inv=invoice.name, user=self.env.user.name,
                reason=self.reason, gap=chr(10) * 2))
        if credit:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': credit.id,
                'view_mode': 'form',
            }
        return {'type': 'ir.actions.act_window_close'}
