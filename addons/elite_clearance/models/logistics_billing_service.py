from odoo import api, fields, models
from odoo.exceptions import UserError


class LogisticsBillingService(models.Model):
    """A revenue line the billing agent may put on a clearance invoice.

    Billing proposes; Operations decides. Anyone in Billing can write down a
    new service, but until an Operations Manager approves it, it cannot
    reach a client invoice - so the list of things the company charges for
    stays a deliberate list rather than whatever was typed under deadline.
    """
    _name = 'logistics.billing.service'
    _description = "Billable Service"
    _inherit = ['mail.thread']
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(
        help="What this covers, so the next biller charges it for the same "
             "thing you did.")
    account_id = fields.Many2one(
        'account.account', string="Income Account", tracking=True,
        domain="[('account_type', 'in', ('income', 'income_other'))]",
        help="Where it is credited. Empty falls back to the company's "
             "clearance fee income account.")
    unit_label = fields.Char(
        string="Unit", default="Par dossier",
        help="Printed on the invoice as Unité.")
    default_amount = fields.Monetary(
        currency_field='currency_id',
        help="Proposed on the billing screen. The biller may change it.")

    state = fields.Selection([
        ('draft', "Draft"),
        ('approved', "Approved"),
        ('refused', "Refused"),
    ], default='draft', required=True, tracking=True)

    requested_by_id = fields.Many2one(
        'res.users', string="Proposed by", readonly=True,
        default=lambda self: self.env.user)
    approved_by_id = fields.Many2one(
        'res.users', string="Approved by", readonly=True)
    approved_date = fields.Datetime(readonly=True)
    refusal_reason = fields.Text(readonly=True)

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        "That service already exists for this company.")

    # ------------------------------------------------------------------
    def action_approve(self):
        for service in self:
            service.company_id._clearance_check_approver('billing_service')
            if service.state == 'approved':
                raise UserError(self.env._(
                    "%s is already approved.", service.name))
            service.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
                'refusal_reason': False,
            })
            service.message_post(body=self.env._(
                "Approved for billing by %s.", self.env.user.name))
        return True

    def action_refuse(self):
        for service in self:
            service.company_id._clearance_check_approver('billing_service')
            service.write({'state': 'refused', 'approved_by_id': False,
                           'approved_date': False})
            service.message_post(body=self.env._(
                "Refused by %s.", self.env.user.name))
        return True

    def action_reset_draft(self):
        self.write({'state': 'draft', 'approved_by_id': False,
                    'approved_date': False})
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_only_if_never_approved(self):
        for service in self:
            if service.state == 'approved':
                raise UserError(self.env._(
                    "%s has been approved for billing. Archive it rather "
                    "than deleting it, so past invoices keep their "
                    "meaning.", service.name))
