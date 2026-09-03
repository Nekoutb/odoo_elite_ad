from odoo import fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    logistics_file_id = fields.Many2one(
        'logistics.file', string="Clearance File", index=True, copy=False,
        help="The clearance file this invoice bills. A file may carry "
             "several invoices over its life (the legacy system did), so "
             "this is the link of record; logistics.file.invoice_id is the "
             "current one the workflow acts on.")

    # --- legacy (Teese) provenance -------------------------------------
    # An invoice issued by the legacy system, imported as a DRAFT customer
    # invoice so it shows in Invoicing and on its file with the billing
    # reference the client knows. It is record-keeping: the revenue and the
    # receivable it produced are in the trial balance uploaded at the cutoff
    # date, so posting it would count them twice. action_post refuses.
    is_legacy = fields.Boolean(
        string="Imported (Teese)", index=True, copy=False,
        help="Issued by the legacy system. Kept as a draft for the record; "
             "it can never be posted, because its revenue is already in the "
             "trial balance uploaded at the cutoff date.")
    legacy_id = fields.Integer(string="Legacy ID", index=True, copy=False)
    legacy_amount_untaxed = fields.Monetary(
        string="Teese Fee Base (HT)", copy=False, currency_field='currency_id',
        help="As exported from the legacy system.")
    legacy_amount_total = fields.Monetary(
        string="Teese Total (TTC)", copy=False, currency_field='currency_id',
        help="As exported from the legacy system. The draft's own total is "
             "built to match it line for line.")
    legacy_amount_residual = fields.Monetary(
        string="Outstanding at Export", copy=False, currency_field='currency_id',
        help="What the legacy system still showed as due when exported. "
             "Informational: the receivable itself is in the uploaded "
             "trial balance, not here.")
    legacy_payment_state = fields.Selection(
        [('not_paid', "Not Paid"), ('partial', "Partially Paid"), ('paid', "Paid")],
        string="Teese Payment State", copy=False)

    def action_post(self):
        legacy = self.filtered('is_legacy')
        if legacy:
            raise UserError(self.env._(
                "%s was issued by the legacy system and is kept as a draft "
                "for the record. Its revenue is in the trial balance "
                "uploaded at the cutoff date; posting it would count that "
                "revenue twice.", ", ".join(legacy.mapped('name'))))
        return super().action_post()
