from odoo import fields, models
from odoo.exceptions import UserError


class LogisticsFileReopenWizard(models.TransientModel):
    """Reopening a closed file is an exception and must be approved: only a
    Clearance Manager can run this, and the reason is posted to the file."""

    _name = 'logistics.file.reopen.wizard'
    _description = "Reopen Clearance File"

    file_id = fields.Many2one('logistics.file', required=True, readonly=True)
    reason = fields.Text(required=True)

    def action_reopen(self):
        self.ensure_one()
        if not self.env.user.has_group('elite_clearance.group_clearance_manager'):
            raise UserError(self.env._(
                "Only a Clearance Manager can approve reopening a file."))
        file = self.file_id
        if file.state == 'ops_closed':
            target = 'in_progress'
        elif file.state == 'done':
            target = 'ops_closed'
        else:
            raise UserError(self.env._(
                "%s is not closed — nothing to reopen.", file.name))
        file.write({'state': target,
                    'reopen_count': file.reopen_count + 1,
                    'date_closed': False})
        file.message_post(body=self.env._(
            "File reopened (approval by %(user)s): %(reason)s",
            user=self.env.user.name, reason=self.reason))
        return {'type': 'ir.actions.act_window_close'}
