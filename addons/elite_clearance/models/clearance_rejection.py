from odoo import api, models
from odoo.exceptions import UserError

# Every refusal in the application, as (model, method). Owner spec
# 10/10/2026: an approver who refuses says why, and the person who asked
# reads it. The dialog only ever calls one of these.
REJECTIONS = {
    ('logistics.file', 'action_refuse_opening'),
    ('logistics.file', 'action_refuse_waiver'),
    ('logistics.file', 'action_refuse_advance_waiver'),
    ('logistics.file', 'action_refuse_reopen_imported'),
    ('logistics.file', 'action_refuse_recharge'),
    ('logistics.expense', 'action_refuse'),
    ('logistics.expense', 'action_return_settlement'),
    ('logistics.expense', 'action_refuse_justification'),
    ('logistics.billing.service', 'action_refuse'),
}


class ClearanceRejectionMixin(models.AbstractModel):
    """A Refuse button opens a dialog for the reason, and the reason
    reaches the person who asked.

    The refusal methods themselves are unchanged in what they do: the
    dialog calls them with the reason in the context, and each posts it
    in the chatter with the requester notified. Called without a reason
    - by a test, a hook, a script - they behave as they always did.
    """

    _name = 'clearance.rejection.mixin'
    _description = "Clearance Rejection with a Reason"

    def action_open_rejection(self):
        method = self.env.context.get('rejection_method')
        if (self._name, method) not in REJECTIONS:
            raise UserError(self.env._("Nothing can be refused that way."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Refuse - give the reason"),
            'res_model': 'clearance.rejection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_ids': ",".join(str(i) for i in self.ids),
                'default_method': method,
            },
        }

    def _clearance_rejection_reason(self):
        return (self.env.context.get('clearance_rejection_reason') or "").strip()

    def _clearance_post_rejection(self, body, requesters=None, reason=None):
        """Post the refusal, with its reason, and notify who asked."""
        self.ensure_one()
        if reason is None:
            reason = self._clearance_rejection_reason()
        if reason:
            body = self.env._("%(body)s Reason: %(reason)s",
                              body=body, reason=reason)
        partners = (requesters or self.env['res.users']).filtered(
            lambda u: u.active and u != self.env.user).partner_id
        self.message_post(body=body, partner_ids=partners.ids,
                          subtype_xmlid='mail.mt_comment')

    @api.model
    def _clearance_users(self, kind):
        """Whoever works a queue - the requester when it is a team."""
        return self.env['clearance.task']._kind_users(kind)
