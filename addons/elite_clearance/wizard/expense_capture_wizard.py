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
        string="Additional Comments", required=True,
        help="Anything the category does not already say about this "
             "disbursement.")
    amount = fields.Monetary(
        string="Amount", currency_field='currency_id', required=True)
    date_requested = fields.Date(
        string="Requested On", required=True,
        default=fields.Date.context_today)
    # Owner 02/10/2026: the requester says where the money should leave
    # from and who collects it - a supplier OR a member of staff. Finance
    # may change all of it once the head has approved.
    journal_id = fields.Many2one(
        'account.journal', string="Payment Channel",
        domain="[('type', 'in', ('cash', 'bank'))]", check_company=True,
        help="A till, a bank, Mobile Money or Maviance. Finance may change it.")
    vendor_id = fields.Many2one(
        'res.partner', string="Supplier / Third Party",
        help="Who is paid - customs, a terminal, a shipping line, a "
             "transporter. Leave empty if a member of staff collects the "
             "money instead.")
    # Owner 13/10/2026: an advance stands against the REQUESTER - the
    # holder is not chosen, it is whoever keys it. Who walks to the till
    # for the cash is a separate, administrative question, asked of every
    # disbursement and answered "me" unless the requester says otherwise.
    is_advance = fields.Boolean(
        string="Staff Advance to Me",
        help="No supplier: the money is advanced to you against 421101 "
             "and you justify it with the receipts. Leave unticked when a "
             "supplier is paid.")
    employee_id = fields.Many2one(
        'hr.employee', string="Advance Holder (accountable)", readonly=True,
        default=lambda self: self.env.user.employee_id.id,
        help="The requester: the advance stands against them whoever "
             "collects the cash.")
    collector_id = fields.Many2one(
        'hr.employee', string="Cash Collected By",
        default=lambda self: self.env.user.employee_id.id,
        help="Who comes to the till for the money - you, unless you name "
             "somebody else. Administrative only: the requester stays "
             "accountable.")
    company_id = fields.Many2one(related='file_id.company_id')

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
        if self.vendor_id and self.is_advance:
            raise UserError(self.env._(
                "A supplier is paid OR the money is advanced to you, not "
                "both. Clear one of them."))
        holder = self.env['hr.employee']
        if self.is_advance:
            holder = self.employee_id or self.env.user.employee_id
            if not holder:
                raise UserError(self.env._(
                    "An advance stands against the requester, and you have "
                    "no employee record for it to stand against. Ask the "
                    "administrator to create one, then key the advance."))
        expense = self.env['logistics.expense'].create({
            'file_id': self.file_id.id,
            'category_id': self.category_id.id,
            'description': self.description,
            'amount': self.amount,
            'date_requested': self.date_requested,
            'journal_id': self.journal_id.id,
            'vendor_id': self.vendor_id.id,
            'employee_id': holder.id,
            'collector_id': self.collector_id.id,
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
