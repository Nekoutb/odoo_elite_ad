from odoo import api, fields, models
from odoo.exceptions import UserError


class LogisticsExpenseSettleWizard(models.TransientModel):
    """Disburse / Pay, with the evidence in hand.

    The owner's rule of 01/10/2026: the Cashier or Treasury officer who
    pays out attaches the proof as they do it - the till receipt, the
    transfer advice, the mobile-money confirmation. The button on the
    disbursement opens this dialog, and the dialog refuses to pay with
    nothing attached. The rule itself lives in `action_settle`, so a call
    from anywhere else meets it too.
    """

    _name = 'logistics.expense.settle.wizard'
    _inherit = ['clearance.documents.mixin']
    _description = "Disburse / Pay"

    expense_id = fields.Many2one(
        'logistics.expense', string="Disbursement", required=True,
        readonly=True)
    file_id = fields.Many2one(related='expense_id.file_id')
    currency_id = fields.Many2one(related='expense_id.currency_id')
    amount = fields.Monetary(related='expense_id.amount')
    journal_id = fields.Many2one(related='expense_id.journal_id')
    journal_type = fields.Selection(related='expense_id.journal_id.type')
    vendor_id = fields.Many2one(related='expense_id.vendor_id')
    employee_id = fields.Many2one(related='expense_id.employee_id')
    payment_mode = fields.Selection(related='expense_id.payment_mode')

    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        expense = self.env['logistics.expense'].browse(
            vals.get('expense_id') or self.env.context.get('active_id'))
        if expense:
            vals['expense_id'] = expense.id
        return vals

    def action_pay(self):
        self.ensure_one()
        # A till prints its own evidence: the voucher, which Disburse /
        # Pay generates and the cashier has signed (owner 10/10/2026).
        if not self.attachment_ids and self.journal_type != 'cash':
            raise UserError(self.env._(
                "Attach the payment evidence - the receipt, the transfer "
                "advice or the mobile-money confirmation - before %s is "
                "paid out.", self.expense_id.name))
        # Dropped on the dialog, so pointing at a transient record about
        # to be swept away: re-point them at the disbursement as PAYMENT
        # evidence, through its own inverse.
        self.expense_id.payment_evidence_ids = (
            self.expense_id.payment_evidence_ids | self.attachment_ids)
        self.expense_id.action_settle()
        return {'type': 'ir.actions.act_window_close'}
