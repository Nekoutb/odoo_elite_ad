from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Who may key an expense: the teams that spend. Finance is excluded on
# purpose - the person who pays is not the person who spends.
ORIGINATING_GROUPS = (
    'elite_clearance.group_clearance_operations',
    'elite_clearance.group_clearance_customer_service',
    'elite_clearance.group_clearance_transit',
)
FINANCE_GROUP = 'elite_clearance.group_clearance_finance'

# How an expense is paid is Finance's decision alone. An originating team
# submits WITHOUT these; Finance fills them in once the expense is approved,
# and the Finance Manager signs them before any money moves.
SETTLEMENT_FIELDS = ('payment_mode', 'journal_id', 'vendor_id', 'employee_id')


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
        draft -> submitted             an originating team (never Finance)
              -> approved              a team manager; lands with Finance
              -> settlement_submitted  Finance keyed mode, vendor/holder and
                                       journal and sent it to the Finance
                                       Manager
              -> settlement_approved   the Finance Manager signed it
              -> settled               the Cashier (till) or Treasury (bank)
                                       paid it out
              -> justified             advances only, with documents

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
        tracking=True,
        help="Set by Finance once the expense is approved. Blank until then.")
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
         ('settlement_submitted', "Awaiting Finance Manager"),
         ('settlement_approved', "Settlement Approved"),
         ('settled', "Settled"),
         ('justified', "Justified"),
         ('cancel', "Cancelled")],
        default='draft', required=True, tracking=True, index=True)
    settlement_move_id = fields.Many2one(
        'account.move', string="Settlement Entry", readonly=True, copy=False)
    justification_move_id = fields.Many2one(
        'account.move', string="Justification Entry", readonly=True, copy=False)
    date_requested = fields.Date(
        string="Requested On", copy=False,
        help="When the disbursement was asked for. With Settled On, this is "
             "the disbursement lag.")
    date_settled = fields.Datetime(readonly=True, copy=False)
    is_final = fields.Boolean(compute='_compute_is_final', store=True)

    # --- legacy (Teese) provenance -------------------------------------
    is_legacy = fields.Boolean(
        string="Legacy", copy=False, index=True,
        help="Imported from the legacy system: historical, billed there, "
             "posted nowhere here. Never feeds a new invoice or the "
             "unjustified-advance gate.")
    legacy_id = fields.Integer(string="Legacy ID", index=True, copy=False)
    legacy_justified = fields.Boolean(
        string="Justified (legacy)", copy=False,
        help="The legacy system's own justification flag, kept verbatim.")
    legacy_reversal = fields.Boolean(
        string="Reversal (legacy)", copy=False,
        help="The legacy row carried a negative or zero amount - a return "
             "or correction. Kept with its absolute value, cancelled, so "
             "the audit trail is complete and no total counts it.")

    # Legacy rows may carry a zero amount (reversals kept for the record);
    # every live expense must be strictly positive.
    _amount_positive = models.Constraint(
        'CHECK(amount > 0 OR is_legacy)',
        "The expense amount must be positive.")

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

    def _check_originating_team(self):
        """Only a spending team keys an expense, and Finance never does.

        Skipped under su: hooks, migrations and the test superuser are not
        people. Every real user - administrators included - is bound.
        """
        if self.env.su:
            return
        user = self.env.user
        # Administrators configure the system; they are not operatives, and
        # they are seeded into every group so the rule would always fire on
        # them. Production staff are never administrators.
        if user.has_group('base.group_system'):
            return
        if user.has_group(FINANCE_GROUP):
            raise UserError(self.env._(
                "Finance does not key expenses. The team that incurred the "
                "cost enters it; Finance decides how it is paid."))
        if not any(user.has_group(g) for g in ORIGINATING_GROUPS):
            raise UserError(self.env._(
                "Only the Operations, Customer Service or Transit team may "
                "enter an expense."))

    def _check_settlement_fields(self, vals):
        """The payment mode, vendor, holder and journal are Finance's."""
        if self.env.su:
            return
        touched = [f for f in SETTLEMENT_FIELDS if f in vals]
        if touched and not self.env.user.has_group(FINANCE_GROUP):
            raise UserError(self.env._(
                "How an expense is paid is decided by Finance, not by the "
                "team submitting it. Leave %s blank.",
                ", ".join(self._fields[f].string for f in touched)))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_originating_team()
        for vals in vals_list:
            self._check_settlement_fields(vals)
            if vals.get('name', "New") == "New":
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'logistics.expense') or "New"
        records = super().create(vals_list)
        if self.env.context.get('legacy_import'):
            return records   # history: the file's state is whatever it was
        for exp in records:
            if exp.file_id.state != 'in_progress':
                raise UserError(self.env._(
                    "Expenses can only be captured on a file that is in "
                    "progress (%s).", exp.file_id.name))
        return records

    def write(self, vals):
        self._check_settlement_fields(vals)
        return super().write(vals)

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

    def _check_disburser(self):
        """Cash leaves through the Cashier, bank money through Treasury."""
        for exp in self:
            kind = 'cash_disburse' if exp.journal_id.type == 'cash' else 'bank_disburse'
            exp.company_id._clearance_check_approver(kind)

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

    def action_submit_settlement(self):
        """Finance has keyed how it is paid; hand it to the Finance Manager."""
        for exp in self:
            if exp.state != 'approved':
                raise UserError(self.env._(
                    "%s is not approved by its team manager yet.", exp.name))
            if not self.env.su and not self.env.user.has_group(FINANCE_GROUP):
                raise UserError(self.env._(
                    "Only Finance sets how an expense is paid."))
            missing = []
            if not exp.payment_mode:
                missing.append(exp._fields['payment_mode'].string)
            if not exp.journal_id:
                missing.append(exp._fields['journal_id'].string)
            if exp.payment_mode == 'direct' and not exp.vendor_id:
                missing.append(exp._fields['vendor_id'].string)
            if exp.payment_mode == 'advance' and not exp.employee_id:
                missing.append(exp._fields['employee_id'].string)
            if missing:
                raise UserError(self.env._(
                    "Key %(what)s on %(exp)s before sending it to the "
                    "Finance Manager.", what=", ".join(missing), exp=exp.name))
            exp.state = 'settlement_submitted'
            exp.message_post(body=self.env._(
                "Settlement sent to the Finance Manager for approval."))

    def action_return_settlement(self):
        """The Finance Manager sends it back to Finance to correct."""
        for exp in self:
            exp.company_id._clearance_check_approver('settlement')
            if exp.state != 'settlement_submitted':
                raise UserError(self.env._(
                    "%s is not awaiting the Finance Manager.", exp.name))
            exp.state = 'approved'
            exp.message_post(body=self.env._(
                "Settlement returned to Finance by the Finance Manager."))

    def action_approve_settlement(self):
        """The Finance Manager signs how Finance proposes to pay."""
        for exp in self:
            exp.company_id._clearance_check_approver('settlement')
            if exp.state != 'settlement_submitted':
                raise UserError(self.env._(
                    "%s has not been sent to the Finance Manager by "
                    "Finance yet.", exp.name))
            if not exp.payment_mode or not exp.journal_id:
                raise UserError(self.env._(
                    "Finance must set the payment mode and the settlement "
                    "journal on %s before it can be approved.", exp.name))
            exp.state = 'settlement_approved'
            labels = dict(exp._fields['payment_mode'].selection)
            holder = ""
            if exp.payment_mode == 'advance':
                holder = ", held by %s" % exp.employee_id.name
            exp.message_post(body=self.env._(
                "Settlement approved: %(mode)s via %(journal)s%(holder)s.",
                mode=labels[exp.payment_mode],
                journal=exp.journal_id.name, holder=holder))

    def action_settle(self):
        """Money leaves the company - through the Cashier for a till, through
        Treasury for a bank or mobile-money journal. Direct: hits 47xx.
        Advance: hits 421101 against the holder until justified."""
        self._check_disburser()
        for exp in self:
            if exp.state != 'settlement_approved':
                raise UserError(self.env._(
                    "The settlement of %s has not been approved by the "
                    "Finance Manager.", exp.name))
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
            if exp.state in ('settlement_submitted', 'settlement_approved'):
                raise UserError(self.env._(
                    "%s is with the Finance Manager or already approved for "
                    "settlement. Have it returned first.", exp.name))
            if exp.settlement_move_id:
                raise UserError(self.env._(
                    "%s has been settled — the journal entry exists. "
                    "Reverse the entry from Accounting first.", exp.name))
            exp.state = 'draft'
