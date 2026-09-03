from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class LogisticsExpenseCategory(models.Model):
    _name = 'logistics.expense.category'
    _description = "Clearance Expense Category"
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True)

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        "An expense category with this code already exists.")


class LogisticsExpense(models.Model):
    """One out-of-pocket expense on a clearance file.

    Lifecycle:
        draft -> submitted -> approved -> settled            (paid direct)
        draft -> submitted -> approved -> settled -> justified  (via advance)

    Postings (all carry the file's analytic account):
        direct settle:   Dr 47xx Débours engagés    / Cr settlement journal
        advance settle:  Dr 421101 Personnel        / Cr settlement journal
                            débours avancés
                            (auxiliary = the staff member's work contact)
        justification:   Dr 47xx Débours engagés    / Cr 421101

    The justification entry is the reclassification that turns a staff debt
    into an engaged, billable disbursement. Only 47xx is ever recharged to
    the client; anything still sitting on 421101 is the staff member's own
    liability and blocks billing until justified or waived.
    """

    _name = 'logistics.expense'
    _description = "Clearance Out-of-Pocket Expense"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'file_id, id'

    name = fields.Char(
        string="Reference", required=True, copy=False, readonly=True,
        default="New", index=True)
    file_id = fields.Many2one(
        'logistics.file', required=True, index=True, ondelete='restrict',
        domain="[('state', '=', 'in_progress')]", tracking=True)
    company_id = fields.Many2one(related='file_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    category_id = fields.Many2one(
        'logistics.expense.category', required=True, tracking=True)
    description = fields.Char(required=True)
    amount = fields.Monetary(required=True, tracking=True)
    vendor_id = fields.Many2one(
        'res.partner', string="Paid To (Vendor)", tracking=True,
        help="The third party ultimately receiving the money — customs, "
             "terminal, shipping line, transporter.")
    payment_mode = fields.Selection(
        [('direct', "Direct (bank / cash / mobile money)"),
         ('advance', "Via employee cash advance")],
        required=True, default='direct', tracking=True)
    journal_id = fields.Many2one(
        'account.journal', string="Settlement Journal",
        domain="[('type', 'in', ('cash', 'bank'))]", check_company=True,
        help="Where the money leaves from: Cash, Bank, Mobile Money or "
             "Maviance — each configured as a cash/bank journal.")
    employee_id = fields.Many2one(
        'hr.employee', string="Advance Holder", tracking=True,
        help="Employee who receives the cash advance and must justify it.")
    state = fields.Selection(
        [('draft', "Draft"),
         ('submitted', "Submitted"),
         ('approved', "Approved"),
         ('settled', "Settled"),
         ('justified', "Justified"),
         ('cancel', "Cancelled")],
        default='draft', required=True, tracking=True, index=True)
    settlement_move_id = fields.Many2one(
        'account.move', string="Settlement Entry", readonly=True, copy=False)
    justification_move_id = fields.Many2one(
        'account.move', string="Justification Entry", readonly=True, copy=False)
    date_settled = fields.Datetime(readonly=True, copy=False)
    is_final = fields.Boolean(compute='_compute_is_final', store=True)

    _amount_positive = models.Constraint(
        'CHECK(amount > 0)', "The expense amount must be positive.")

    @api.depends('state', 'payment_mode')
    def _compute_is_final(self):
        for exp in self:
            exp.is_final = (
                exp.state == 'justified'
                or (exp.state == 'settled' and exp.payment_mode == 'direct')
                or exp.state == 'cancel')

    @api.constrains('payment_mode', 'employee_id')
    def _check_advance_holder(self):
        """Money advanced against 421101 has to stand against somebody.

        The holder is required from the moment the expense is keyed, not from
        the moment it is submitted: an advance with no registered staff
        member has no auxiliary, so there is no ledger to carry it and no one
        to chase for the receipts.
        """
        for exp in self:
            if exp.payment_mode == 'advance' and not exp.employee_id:
                raise ValidationError(self.env._(
                    "An advance must be held by a registered staff member "
                    "(%s). Create the employee first, then hand over the "
                    "money.", exp.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', "New") == "New":
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'logistics.expense') or "New"
        records = super().create(vals_list)
        for exp in records:
            if exp.file_id.state != 'in_progress':
                raise UserError(self.env._(
                    "Expenses can only be captured on a file that is in "
                    "progress (%s).", exp.file_id.name))
        return records

    def unlink(self):
        if any(exp.state not in ('draft', 'cancel') for exp in self):
            raise UserError(self.env._(
                "A submitted expense cannot be deleted — cancel it instead."))
        return super().unlink()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _get_company_account(self, field_name, label):
        account = self.company_id[field_name]
        if not account:
            raise UserError(self.env._(
                "Configure the %s under Clearance → Configuration → "
                "Settings before posting.", label))
        return account

    def _analytic_distribution(self):
        self.ensure_one()
        account = self.file_id.analytic_account_id
        return {str(account.id): 100} if account else False

    def _check_finance(self):
        for exp in self:
            exp.company_id._clearance_check_approver('finance')

    def _check_manager(self):
        for exp in self:
            exp.company_id._clearance_check_approver('expense')

    # ------------------------------------------------------------------
    # workflow
    # ------------------------------------------------------------------
    def action_submit(self):
        for exp in self:
            if exp.state != 'draft':
                raise UserError(self.env._("%s is not in draft.", exp.name))
            exp.state = 'submitted'

    def action_approve(self):
        self._check_manager()
        for exp in self:
            if exp.state != 'submitted':
                raise UserError(self.env._(
                    "%s has not been submitted for approval.", exp.name))
            exp.state = 'approved'

    def action_refuse(self):
        self._check_manager()
        self.write({'state': 'cancel'})

    def action_settle(self):
        """Money leaves the company. Direct: hits OOP. Advance: hits the
        employee's advance account until justified."""
        self._check_finance()
        for exp in self:
            if exp.state != 'approved':
                raise UserError(self.env._("%s is not approved.", exp.name))
            if not exp.journal_id:
                raise UserError(self.env._(
                    "Choose the settlement journal on %s — Cash, Bank, "
                    "Mobile Money or Maviance.", exp.name))
            if exp.payment_mode == 'direct':
                debit_account = exp._get_company_account(
                    'clearance_oop_account_id', "Out-of-Pocket Expenses account")
                partner = exp.vendor_id
                analytic = exp._analytic_distribution()
            else:
                debit_account = exp._get_company_account(
                    'clearance_advance_account_id', "Employee Advances account")
                # The auxiliary on 421101. Created on demand rather than
                # refused, because hr only makes the work contact as a side
                # effect of writing a work e-mail or phone.
                partner = exp.employee_id._clearance_auxiliary_partner()
                analytic = False  # the analytic tag lands at justification
            credit_account = exp.journal_id.default_account_id
            if not credit_account:
                raise UserError(self.env._(
                    "Journal %s has no default account.", exp.journal_id.name))
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': exp.journal_id.id,
                'date': fields.Date.context_today(exp),
                'ref': self.env._("%(exp)s — %(file)s — %(desc)s",
                                  exp=exp.name, file=exp.file_id.name,
                                  desc=exp.description),
                'line_ids': [
                    fields.Command.create({
                        'name': exp.description,
                        'account_id': debit_account.id,
                        'partner_id': partner.id if partner else False,
                        'debit': exp.amount, 'credit': 0.0,
                        'analytic_distribution': analytic,
                    }),
                    fields.Command.create({
                        'name': exp.description,
                        'account_id': credit_account.id,
                        'partner_id': partner.id if partner else False,
                        'debit': 0.0, 'credit': exp.amount,
                    }),
                ],
            })
            move.action_post()
            exp.write({
                'settlement_move_id': move.id,
                'state': 'settled',
                'date_settled': fields.Datetime.now(),
            })

    def action_justify(self):
        """Supporting documents are in: move the advance onto the file's
        out-of-pocket account. Requires at least one attachment."""
        self._check_finance()
        for exp in self:
            if exp.state != 'settled' or exp.payment_mode != 'advance':
                raise UserError(self.env._(
                    "%s is not a settled cash advance.", exp.name))
            attachments = self.env['ir.attachment'].search_count([
                ('res_model', '=', self._name), ('res_id', '=', exp.id)])
            if not attachments:
                raise UserError(self.env._(
                    "Attach the supporting documents to %s before "
                    "justifying the advance.", exp.name))
            oop = exp._get_company_account(
                'clearance_oop_account_id', "Out-of-Pocket Expenses account")
            adv = exp._get_company_account(
                'clearance_advance_account_id', "Employee Advances account")
            journal = exp.company_id.clearance_misc_journal_id
            if not journal:
                journal = self.env['account.journal'].search([
                    ('type', '=', 'general'),
                    ('company_id', '=', exp.company_id.id)], limit=1)
            if not journal:
                raise UserError(self.env._(
                    "Configure the Clearance Miscellaneous Journal in "
                    "Settings."))
            partner = exp.employee_id._clearance_auxiliary_partner()
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': fields.Date.context_today(exp),
                'ref': self.env._("Justification %(exp)s — %(file)s",
                                  exp=exp.name, file=exp.file_id.name),
                'line_ids': [
                    fields.Command.create({
                        'name': exp.description,
                        'account_id': oop.id,
                        'partner_id': exp.vendor_id.id or False,
                        'debit': exp.amount, 'credit': 0.0,
                        'analytic_distribution': exp._analytic_distribution(),
                    }),
                    fields.Command.create({
                        'name': exp.description,
                        'account_id': adv.id,
                        'partner_id': partner.id if partner else False,
                        'debit': 0.0, 'credit': exp.amount,
                    }),
                ],
            })
            move.action_post()
            exp.write({'justification_move_id': move.id, 'state': 'justified'})
            exp.message_post(body=self.env._(
                "Advance justified: %(amount)s reclassified from 421101 "
                "(held by %(who)s) to the engaged disbursements account. "
                "It is now billable.",
                amount=exp.amount, who=exp.employee_id.name))

    def action_reset_to_draft(self):
        for exp in self:
            if exp.settlement_move_id:
                raise UserError(self.env._(
                    "%s has been settled — the journal entry exists. "
                    "Reverse the entry from Accounting first.", exp.name))
            exp.state = 'draft'
