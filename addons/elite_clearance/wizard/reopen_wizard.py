from odoo import fields, models
from odoo.exceptions import UserError


class LogisticsFileReopenWizard(models.TransientModel):
    """Reopening a closed file is an exception and must be approved.

    The Operations Manager signs it (owner spec 14/09/2026): closing a
    billed file is the Billing Agent's own decision, but going back into
    a closed one - for more billing, a credit note, any adjustment - is
    an operational judgement. The reason is posted to the file."""

    _name = 'logistics.file.reopen.wizard'
    _description = "Reopen Clearance File"

    file_id = fields.Many2one('logistics.file', required=True, readonly=True)
    file_state = fields.Selection(related='file_id.state', string="File Status")
    reason = fields.Text(required=True)
    # A completed file is reopened for one of two reasons, and they are
    # not the same reopening (owner 13/09/2026): either the bill was
    # wrong, or more cost has landed on the job. Asking makes the second
    # one click instead of two, and says which it was on the record.
    target_state = fields.Selection(
        [('ops_closed', "Back to billing"),
         ('in_progress', "Back to operations, to add costs")],
        string="Reopen for", default='ops_closed',
        help="Only asked of a completed file. A file that is merely closed "
             "for operations always goes back to operations.")

    def action_reopen(self):
        self.ensure_one()
        file = self.file_id
        file.company_id._clearance_check_approver('reopen')
        if file.state == 'ops_closed':
            target = 'in_progress'
        elif file.state == 'done':
            target = self.target_state or 'ops_closed'
        else:
            raise UserError(self.env._(
                "%s is not closed — nothing to reopen.", file.name))
        file.write({'state': target,
                    'reopen_count': file.reopen_count + 1,
                    'date_closed': False})
        file.message_post(body=self.env._(
            "File reopened to %(target)s (approval by %(user)s): %(reason)s",
            target=dict(file._fields['state'].selection).get(target, target),
            user=self.env.user.name, reason=self.reason))
        return {'type': 'ir.actions.act_window_close'}
