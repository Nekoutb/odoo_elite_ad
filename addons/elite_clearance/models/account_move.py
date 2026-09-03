from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    logistics_file_id = fields.Many2one(
        'logistics.file', string="Clearance File", index=True, copy=False,
        help="The clearance file this invoice bills. A file may carry "
             "several invoices over its life (the legacy system did), so "
             "this is the link of record; logistics.file.invoice_id is the "
             "latest of them.")
    legacy_id = fields.Integer(
        string="Legacy ID", index=True, copy=False,
        help="Identifier of this invoice in the legacy Teese system. Set "
             "only by the migration; makes re-imports idempotent.")
    legacy_amount_total = fields.Monetary(
        string="Legacy Total", copy=False, currency_field='currency_id',
        help="Total as recorded in the legacy system at export time, kept "
             "for reconciliation. Odoo recomputes its own total from lines.")
    legacy_amount_residual = fields.Monetary(
        string="Legacy Outstanding", copy=False, currency_field='currency_id',
        help="Amount still due in the legacy system at export time. Not a "
             "posting: the accountant's opening balances carry the debt.")
