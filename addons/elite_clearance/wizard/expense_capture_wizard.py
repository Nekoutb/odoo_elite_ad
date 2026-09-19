from odoo import api, fields, models
from odoo.exceptions import UserError


class LogisticsExpenseCaptureWizard(models.TransientModel):
    """Key a disbursement and submit it, in one press.

    The owner's rule of 19/09/2026: the dialog offers **Submit** and
    **Submit & Add New**, and nothing else. Keying a cost and then saving
    the file and then finding the row again and pressing Submit is three
    acts for one intention, and the middle one exists only because of how
    the screen was built.

    It is a wizard rather than the file's own list-in-a-dialog because a
    row keyed in an x2many dialog HAS NO DATABASE ID until the parent
    form is saved - Odoo's dialog saves it into the parent's list in
    memory - so a button there cannot submit anything. A transient record
    exists the moment it is created, which is what lets one press do the
    whole thing.
    """

    _name = 'logistics.expense.capture.wizard'
    _inherit = ['clearance.documents.mixin']
    _description = "Capture a Disbursement"

    file_id = fields.Many2one(
        'logistics.file', string="Clearance File", required=True, readonly=True)
    currency_id = fields.Many2one(related='file_id.currency_id')
    category_id = fields.Many2one(
        'logistics.expense.category', string="Category", required=True)
    description = fields.Char(
        string="Description", required=True,
        help="What the money was spent on.")
    amount = fields.Monetary(
        string="Amount", currency_field='currency_id', required=True)
    date_requested = fields.Date(
        string="Requested On", required=True,
        default=fields.Date.context_today)

    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        file = self.env['logistics.file'].browse(
            vals.get('file_id') or self.env.context.get('active_id'))
        if file:
            vals['file_id'] = file.id
        return vals

    # ------------------------------------------------------------------
    def _capture(self):
        """Create the disbursement, move the documents on to it, submit."""
        self.ensure_one()
        if self.currency_id.compare_amounts(self.amount, 0.0) <= 0:
            raise UserError(self.env._(
                "A disbursement of nothing is not a disbursement. Key "
                "what was actually paid."))
        expense = self.env['logistics.expense'].create({
            'file_id': self.file_id.id,
            'category_id': self.category_id.id,
            'description': self.description,
            'amount': self.amount,
            'date_requested': self.date_requested,
        })
        # The receipts were dropped on the wizard, so they are pointing at
        # a transient record that is about to be swept away. Re-point them
        # at the disbursement through its own inverse, which is what
        # stamps the arrival date and keeps one set of documents.
        dropped = self.attachment_ids
        if dropped:
            expense.attachment_ids = dropped
        expense.action_submit()
        return expense

    def action_submit_close(self):
        self._capture()
        return {'type': 'ir.actions.act_window_close'}

    def action_submit_new(self):
        """Submit this one and open a fresh dialog for the next."""
        self.ensure_one()
        file = self.file_id
        self._capture()
        return file.action_add_expense()
