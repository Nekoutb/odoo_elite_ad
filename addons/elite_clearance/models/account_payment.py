from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    """A client receipt, and which clearance file it belongs to.

    An advance arrives as money in the bank long before anybody thinks
    about a file: the client transfers what the duties will cost and the
    reference says nothing. So the file is attached to the RECEIPT, after
    the fact, by whoever recognises it - and from that moment the payment
    carries the file's analytic on every line and the billing screen
    reads it back as an advance (owner spec 19/09/2026).

    The link itself lives on the journal entry, because that is what the
    analytic hangs off and what a plain bank entry has too; this is the
    stored related that makes it searchable from the payment.
    """

    _inherit = 'account.payment'

    logistics_file_id = fields.Many2one(
        related='move_id.logistics_file_id', store=True, index=True,
        string="Clearance File", readonly=True,
        help="The file this receipt was taken against. Every line of the "
             "entry carries that file's analytic account.")
    clearance_needs_attribution = fields.Boolean(
        compute='_compute_clearance_needs_attribution',
        help="A customer receipt that has not been put against a "
             "clearance file yet.")

    @api.depends('payment_type', 'partner_type', 'state', 'logistics_file_id')
    def _compute_clearance_needs_attribution(self):
        for payment in self:
            payment.clearance_needs_attribution = bool(
                payment.payment_type == 'inbound'
                and payment.partner_type == 'customer'
                and payment.state not in ('draft', 'canceled', 'rejected')
                and not payment.logistics_file_id)

    def action_clearance_attribute(self):
        """Show every open file this client has, and take one."""
        self.ensure_one()
        if self.payment_type != 'inbound' or self.partner_type != 'customer':
            raise UserError(self.env._(
                "%s is not money received from a customer, so there is no "
                "clearance file to put it against.", self.display_name))
        if not self.partner_id:
            raise UserError(self.env._(
                "%s names no customer, so there are no files to show. "
                "Name the customer first.", self.display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Which file is this advance for?"),
            'res_model': 'logistics.payment.attribution.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id, 'default_payment_id': self.id},
        }
