from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    logistics_file_id = fields.Many2one(
        'logistics.file', string="Clearance File", index=True, copy=False,
        help="The clearance file this invoice bills. A file may carry "
             "several invoices over its life, so this is the link of "
             "record; logistics.file.invoice_id is the latest of them. "
             "Invoices issued by the legacy system are NOT account.move "
             "records: see logistics.legacy.invoice.")
