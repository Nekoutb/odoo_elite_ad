from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    legacy_id = fields.Integer(
        string="Legacy ID", index=True, copy=False,
        help="Identifier of this partner in the legacy Teese system. Set "
             "only by the migration; makes re-imports idempotent.")
