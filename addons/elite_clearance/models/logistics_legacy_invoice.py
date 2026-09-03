from odoo import api, fields, models


class LogisticsLegacyInvoice(models.Model):
    """An invoice issued by the legacy system, kept for the record.

    Deliberately NOT an account.move. The legacy books close on the cutoff
    date and their balances arrive as an uploaded trial balance; a draft
    invoice in Odoo could be posted by mistake and count that revenue and
    receivable twice. This model cannot post anything, has exactly one
    state — Imported — and exists so that opening a clearance file shows
    what was billed on it, with the billing reference the client knows.
    """

    _name = 'logistics.legacy.invoice'
    _description = "Imported Invoice (legacy)"
    _order = 'date_invoice desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string="Billing Reference", required=True, readonly=True, index=True)
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    file_id = fields.Many2one(
        'logistics.file', string="Clearance File", readonly=True, index=True,
        ondelete='set null')
    partner_id = fields.Many2one('res.partner', string="Client", readonly=True, index=True)
    move_type = fields.Selection(
        [('invoice', "Invoice"), ('refund', "Credit Note")],
        default='invoice', required=True, readonly=True)
    state = fields.Selection(
        [('imported', "Imported")], default='imported', required=True, readonly=True,
        help="Always Imported. This record is history; it is never posted.")
    date_invoice = fields.Date(string="Invoice Date", readonly=True)
    date_due = fields.Date(string="Due Date", readonly=True)
    amount_untaxed = fields.Monetary(
        string="Fee Base (HT)", readonly=True, currency_field='currency_id',
        help="As exported. In the legacy system this is the taxable fee "
             "base; disbursements are outside it.")
    amount_total = fields.Monetary(string="Total (TTC)", readonly=True, currency_field='currency_id')
    amount_residual = fields.Monetary(
        string="Outstanding at Export", readonly=True, currency_field='currency_id',
        help="What the legacy system still showed as due when it was "
             "exported. Informational: the receivable itself is in the "
             "uploaded trial balance, not here.")
    payment_state = fields.Selection(
        [('not_paid', "Not Paid"), ('partial', "Partially Paid"), ('paid', "Paid")],
        default='not_paid', readonly=True)
    legacy_id = fields.Integer(string="Legacy ID", readonly=True, index=True)
    line_ids = fields.One2many(
        'logistics.legacy.invoice.line', 'invoice_id', string="Lines", readonly=True)
    line_count = fields.Integer(compute='_compute_line_count')

    _legacy_id_company_uniq = models.Constraint(
        'UNIQUE(legacy_id, company_id)',
        "This legacy invoice has already been imported.")

    @api.depends('line_ids')
    def _compute_line_count(self):
        for inv in self:
            inv.line_count = len(inv.line_ids)


class LogisticsLegacyInvoiceLine(models.Model):
    _name = 'logistics.legacy.invoice.line'
    _description = "Imported Invoice Line (legacy)"
    _order = 'invoice_id, id'

    invoice_id = fields.Many2one(
        'logistics.legacy.invoice', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='invoice_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='invoice_id.currency_id')
    name = fields.Char(string="Label", readonly=True)
    product_label = fields.Char(
        string="Legacy Product", readonly=True,
        help="The legacy product the line was billed under, by name.")
    product_code = fields.Char(string="Legacy Product Code", readonly=True)
    is_debours = fields.Boolean(
        string="Disbursement", readonly=True,
        help="Pass-through disbursement recharged at cost, as flagged in "
             "the legacy system; the rest is fee revenue.")
    quantity = fields.Float(readonly=True, digits=(16, 4), default=1.0)
    price_unit = fields.Monetary(string="Unit Price", readonly=True, currency_field='currency_id')
    price_subtotal = fields.Monetary(string="Subtotal", readonly=True, currency_field='currency_id')
    legacy_id = fields.Integer(string="Legacy ID", readonly=True, index=True)
