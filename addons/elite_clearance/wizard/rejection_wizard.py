from odoo import fields, models
from odoo.exceptions import UserError

from ..models.clearance_rejection import REJECTIONS


class ClearanceRejectionWizard(models.TransientModel):
    """Why it is refused - asked at the moment of refusing."""

    _name = 'clearance.rejection.wizard'
    _description = "Refuse with a Reason"

    res_model = fields.Char(required=True, readonly=True)
    res_ids = fields.Char(required=True, readonly=True)
    method = fields.Char(required=True, readonly=True)
    reason = fields.Text(
        string="Reason", required=True,
        help="Posted on the record and sent to the person who asked, so "
             "they know what to change.")

    def action_confirm(self):
        self.ensure_one()
        if (self.res_model, self.method) not in REJECTIONS:
            raise UserError(self.env._("Nothing can be refused that way."))
        if not (self.reason or "").strip():
            raise UserError(self.env._("Say why it is refused."))
        ids = [int(i) for i in self.res_ids.split(",") if i.strip()]
        records = self.env[self.res_model].browse(ids).exists()
        getattr(records.with_context(
            clearance_rejection_reason=self.reason.strip()), self.method)()
        return {'type': 'ir.actions.act_window_close'}
