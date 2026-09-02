from odoo import api, fields, models
from odoo.exceptions import UserError


class LogisticsFileDocumentDateWizard(models.TransientModel):
    """Set one reception date/time on several checklist lines at once."""

    _name = 'logistics.file.document.date.wizard'
    _description = "Set Reception Date/Time"

    file_id = fields.Many2one('logistics.file', required=True, readonly=True)
    date_received = fields.Datetime(
        string="Received On", required=True, default=fields.Datetime.now,
    )
    line_ids = fields.Many2many(
        'logistics.file.document', string="Apply To",
        domain="[('file_id', '=', file_id)]",
        help="The documents that will carry this date/time. Preselected: "
             "every line already ticked as received.",
    )

    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        file_id = vals.get('file_id') or self.env.context.get('active_id')
        if file_id:
            file = self.env['logistics.file'].browse(file_id)
            vals['file_id'] = file.id
            vals['line_ids'] = [fields.Command.set(
                file.document_ids.filtered('received').ids)]
        return vals

    def action_apply(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(self.env._(
                "Select at least one document to apply the date to."))
        self.line_ids.write({
            'received': True,
            'date_received': self.date_received,
        })
        return {'type': 'ir.actions.act_window_close'}
