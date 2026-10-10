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
# every role at once; exempt wherever an administrator is
ADMIN_GROUP = 'elite_clearance.group_clearance_admin'
# Which head signs for which team (owner spec 02/10/2026): the Head of
# Service Operations approves what an Operations agent keyed, and so on.
TEAM_OF_GROUP = {
    'elite_clearance.group_clearance_operations': 'operations',
    'elite_clearance.group_clearance_customer_service': 'customer_service',
    'elite_clearance.group_clearance_transit': 'transit',
}
HEAD_OF_TEAM = {
    'operations': 'elite_clearance.group_clearance_ops_manager',
    'customer_service': 'elite_clearance.group_clearance_customer_service_manager',
    'transit': 'elite_clearance.group_clearance_transit_manager',
}

# How an expense is paid is Finance's decision alone. An originating team
# submits WITHOUT these; Finance fills them in once the expense is approved,
# and the Head of Service Finance signs them before any money moves. WHO is paid is
# not in the list: the team that incurred the cost knows the terminal, the
# shipping line or the transporter it dealt with, and names it when keying
# (owner, 06/09/2026). Finance may still correct it at settlement.
# Who is paid and how - all of it Finance's. `vendor_id` was the
# spending team's between 06/09 and 19/09/2026, on the reasoning that
# they know who they handed the money to; the owner has since decided
# that naming a third party on a payment is a Finance act whoever knew
# it first, so it is back in this list.
# Owner 02/10/2026, reversing again: the REQUESTER keys the payment
# channel and the supplier or the staff member who collects the money,
# while the expense is theirs (draft, submitted); from `approved` on
# these are Finance's, and Finance may overwrite every one of them.
SETTLEMENT_FIELDS = ('payment_mode', 'journal_id', 'employee_id',
                     'vendor_id')
# the states in which the originating team may still key them
REQUESTER_STATES = ('draft', 'submitted')

# An advance is the holder's debt until the reclassification is POSTED.
# Submitting the receipts is not being believed, and the Operations
# Manager accepting them is not the entry being made: the money sits on
# 421101 through all three states, so all three block the file.
UNJUSTIFIED_ADVANCE_STATES = (
    'settled', 'justification_submitted', 'justification_ops_approved')


class LogisticsExpenseCategory(models.Model):
    _name = 'logistics.expense.category'
    _description = "Clearance Expense Category"
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    # Some costs come back with a receipt and some never will - a tip at
    # the gate, an extra-legal fee, a phone call. Advancing cash for one
    # of those and then waiting for paperwork that cannot exist is how a
    # file stops moving for nothing (owner spec 15/09/2026).
    justification = fields.Selection(
        [('justifiable', "Justifiable"),
         ('non_justifiable', "Non justifiable")],
        string="Justification", default='justifiable', required=True,
        help="Justifiable: an advance for this is the holder's debt until "
             "they produce the documents. Non justifiable: there will "
             "never be a document, so the money is spent the moment it is "
             "handed over - it goes straight to the engaged-disbursements "
             "account, is billable at once, and holds nothing up.")
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
              -> settlement_submitted  Finance keyed mode and journal,
                                       the holder for an advance, confirmed
                                       the vendor the originator named, and
                                       sent it to the Head of Service Finance
              -> settlement_approved   the Head of Service Finance signed it
              -> settled               the Cashier (till) or Treasury (bank)
                                       paid it out
              -> justified             advances only, with documents

    Postings. EVERY line of every entry below carries the file's analytic
    account - both sides, whatever the account - so the file number is on
    everything clearance puts in the ledger:
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
    _inherit = ['mail.thread', 'mail.activity.mixin',
                'clearance.documents.mixin', 'clearance.rejection.mixin']
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
    # "Additional Comments" on every screen (owner 10/10/2026): the
    # category already says what the money is for.
    description = fields.Char(string="Additional Comments", required=True)
    amount = fields.Monetary(required=True, tracking=True)
    unit_label = fields.Char(
        string="Unit", default="Par dossier",
        help="How the client is told this was charged - Par dossier, Par "
             "Conteneur, Par tonne. Printed on the invoice.")
    vendor_id = fields.Many2one(
        'res.partner', string="Third Party", tracking=True,
        help="Whoever ultimately receives the money - customs, a "
             "terminal, a shipping line, a transporter, or a member of "
             "staff. Named by Finance when the settlement is prepared, "
             "not by the team that keyed the cost.")
    payment_mode = fields.Selection(
        [('cash', "Cash"),
         ('electronic', "Electronic (bank / mobile money)"),
         ('advance', "Via employee cash advance")],
        tracking=True,
        help="How the money leaves. Follows the payment channel and the "
             "staff member keyed at request - a till is cash, a bank or "
             "mobile-money channel is electronic, a staff member is an "
             "advance - and Finance may overwrite it once the expense is "
             "approved.")
    journal_id = fields.Many2one(
        'account.journal', string="Payment Channel",
        domain="[('type', 'in', ('cash', 'bank'))]", check_company=True,
        help="Where the money leaves from: a till, a bank, Mobile Money "
             "or Maviance - each configured as a cash/bank journal. Keyed "
             "by the requester; Finance may change it.")
    employee_id = fields.Many2one(
        'hr.employee', string="Staff Collecting the Funds", tracking=True,
        help="The member of staff who collects the money as an advance "
             "and must justify it. Named by the requester, or by Finance.")
    can_edit_payment = fields.Boolean(
        compute='_compute_can_edit_payment',
        help="Whether the current user may key or change the payment "
             "channel and counterparty in the expense's present state.")
    # attachment_ids comes from clearance.documents.mixin: the receipts
    # and invoices behind the expense, dropped on the dialog or picked
    # with Upload. Their arrival is what stamps date_documents_submitted.
    state = fields.Selection(
        [('draft', "Draft"),
         ('submitted', "Submitted"),
         ('approved', "Approved - with Finance"),
         ('settlement_submitted', "Awaiting Head of Service Finance"),
         ('settlement_approved', "Settlement Approved"),
         ('settled', "Settled"),
         ('justification_submitted', "Justification: Operations"),
         ('justification_ops_approved', "Justification: Head of Service Finance"),
         ('justified', "Justified"),
         ('cancel', "Cancelled")],
        default='draft', required=True, tracking=True, index=True)
    originating_team = fields.Selection(
        [('operations', "Service Operations"),
         ('customer_service', "Customer Service"),
         ('transit', "Service Transit")],
        string="Keyed By", readonly=True, copy=False, index=True,
        help="The service whose agent keyed this cost. Its head is the "
             "one who approves it. Empty when it was keyed by an "
             "administrator or a migration, in which case any head may.")
    accrual_move_id = fields.Many2one(
        'account.move', string="Accrual Entry", readonly=True, copy=False,
        help="Dr Débours à engager / Cr the third party, posted when the "
             "disbursement is approved and the third party is named. "
             "Settling it moves the debit to Débours engagés.")
    settlement_move_id = fields.Many2one(
        'account.move', string="Settlement Entry", readonly=True, copy=False)
    justification_move_id = fields.Many2one(
        'account.move', string="Justification Entry", readonly=True, copy=False)
    # --- the timeline ---------------------------------------------------
    # One stamp per step, written by the action that performs it, so the
    # disbursement lag and the justification lag are facts rather than
    # recollections. All readonly: nobody types these.
    date_requested = fields.Date(
        string="Requested On", copy=False, readonly=True,
        default=fields.Date.context_today,
        help="When the disbursement was asked for. Set when the expense is "
             "keyed; with Paid On this gives the disbursement lag.")
    date_submitted = fields.Datetime(
        string="Submitted On", readonly=True, copy=False,
        help="When the originating team sent it for approval.")
    date_approved = fields.Datetime(
        string="Approved On", readonly=True, copy=False,
        help="When the team manager approved it.")
    date_settlement_submitted = fields.Datetime(
        string="Sent to Head of Service Finance On", readonly=True, copy=False,
        help="When Finance had keyed the payment mode and the journal, "
             "confirmed the counterparty, and sent it for approval.")
    date_settlement_approved = fields.Datetime(
        string="Settlement Approved On", readonly=True, copy=False,
        help="When the Head of Service Finance approved how it would be paid.")
    # The documents, told apart (owner, 01/10/2026): what supported
    # the request, and what proves the payment. `attachment_ids` on the
    # mixin stays the union - the justification count and the chatter
    # see one set.
    request_document_ids = fields.Many2many(
        'ir.attachment', 'logistics_expense_request_doc_rel',
        string="Supporting Documents (request)",
        compute='_compute_request_document_ids',
        inverse='_inverse_request_document_ids',
        help="The receipt, quote or notice the cost was keyed from.")
    payment_evidence_ids = fields.Many2many(
        'ir.attachment', 'logistics_expense_payment_doc_rel',
        string="Payment Evidence",
        compute='_compute_payment_evidence_ids',
        inverse='_inverse_payment_evidence_ids',
        help="What proves the money left: the receipt, the transfer "
             "advice, the mobile-money confirmation. Demanded at "
             "Disburse / Pay.")
    # The petty-cash voucher (owner 10/10/2026). Printed by Disburse / Pay
    # on a till, kept here as the generated copy; the cashier has it
    # signed by whoever takes the cash and uploads the signed copy, and
    # the file cannot be closed for operations until they have.
    journal_type = fields.Selection(related='journal_id.type')
    cash_voucher_ids = fields.Many2many(
        'ir.attachment', 'logistics_expense_voucher_rel',
        string="Cash Voucher (generated)",
        compute='_compute_cash_voucher_ids', inverse='_inverse_cash_voucher_ids',
        help="The voucher the system printed when the cash was paid out. "
             "Download it, have it signed, and upload the signed copy below.")
    signed_voucher_ids = fields.Many2many(
        'ir.attachment', 'logistics_expense_signed_voucher_rel',
        string="Cash Voucher (signed)",
        compute='_compute_signed_voucher_ids', inverse='_inverse_signed_voucher_ids',
        help="The signed voucher, uploaded by the Cashier. Until it is here "
             "the file cannot be closed for operations.")
    # Who did each step, beside when (owner 10/10/2026): the voucher
    # prints every approval with a name and a time stamp.
    approved_by_id = fields.Many2one(
        'res.users', string="Approved By", readonly=True, copy=False)
    settlement_submitted_by_id = fields.Many2one(
        'res.users', string="Settlement Prepared By", readonly=True, copy=False)
    settlement_approved_by_id = fields.Many2one(
        'res.users', string="Settlement Approved By", readonly=True, copy=False)
    settled_by_id = fields.Many2one(
        'res.users', string="Paid By", readonly=True, copy=False)
    payment_evidence_sent_date = fields.Datetime(
        string="Evidence Sent to Third Party On", readonly=True, copy=False)
    payment_evidence_sent_by_id = fields.Many2one(
        'res.users', string="Evidence Sent By", readonly=True, copy=False)
    date_settled = fields.Datetime(
        string="Paid On", readonly=True, copy=False,
        help="When the Cashier or Treasury actually paid it out and the "
             "journal entry was posted.")
    date_documents_submitted = fields.Datetime(
        string="Documents Received On", readonly=True, copy=False,
        help="When the first supporting document was attached to this "
             "expense. Stamped by the upload itself.")
    date_justification_submitted = fields.Datetime(
        string="Justification Submitted On", readonly=True, copy=False,
        help="When Finance sent the supporting documents to the Operations "
             "Manager for review.")
    date_justified = fields.Datetime(
        string="Justification Approved On", readonly=True, copy=False,
        help="When the advance was justified and reclassified from 421101 "
             "to the engaged-disbursements account.")
    is_final = fields.Boolean(compute='_compute_is_final', store=True)
    justification_required = fields.Boolean(
        compute='_compute_justification_required', store=True,
        string="Justifiable",
        help="Read from the expense category. False means no document "
             "will ever exist for this cost, so an advance for it needs "
             "no justification and blocks nothing.")

    # Stored, because the My Tasks queue is raw SQL over this table and
    # cannot call a method to find out.
    @api.depends('category_id.justification')
    def _compute_justification_required(self):
        for expense in self:
            expense.justification_required = (
                expense.category_id.justification != 'non_justifiable')
    recharge_amount = fields.Monetary(
        string="To Recharge", currency_field='currency_id', copy=False,
        help="What the client is charged for this disbursement, when the "
             "biller has changed it. Empty means at cost. Recorded from the "
             "billing screen so it is known later which disbursement was "
             "discounted and by how much.")
    recharge_comment = fields.Char(
        string="Why the Recharge Differs", copy=False,
        help="The biller's reason for charging this disbursement at other "
             "than cost, keyed on its own line of the billing screen "
             "(owner 10/10/2026).")

    # --- billed, or still to bill (owner spec 13/09/2026) ---------------
    # A file is billed as costs are incurred, not once at the end, so the
    # question "has this disbursement been recharged already?" is asked of
    # every disbursement and not of the file. The answer is the invoice
    # LINE: a credit note may reverse one line and leave the rest of the
    # invoice standing, and then this one disbursement is billable again
    # while its neighbours are not.
    billed_line_id = fields.Many2one(
        'account.move.line', string="Billed On Line", readonly=True,
        copy=False, ondelete='set null', index=True,
        help="The invoice line that recharged this disbursement. Never "
             "shown to an agent without accounting rights - what they see "
             "is Billed and, if they may read it, the invoice.")
    billed_invoice_id = fields.Many2one(
        'account.move', compute='_compute_billed', compute_sudo=True,
        string="Billed On")
    is_billed = fields.Boolean(
        compute='_compute_billed', compute_sudo=True, string="Billed",
        help="Recharged to the client on an invoice that still stands. "
             "Cancel that invoice, or credit its line, and this "
             "disbursement can be billed again.")

    # compute_sudo on both: an Operations, Customer Service or Transit
    # agent has no accounting rights at all, and a compute that reads
    # account.move as that user raises AccessError on a screen they open
    # every day.
    @api.depends('billed_line_id', 'billed_line_id.clearance_credited',
                 'billed_line_id.move_id.state',
                 'billed_line_id.move_id.clearance_voided')
    def _compute_billed(self):
        for expense in self:
            line = expense.billed_line_id
            stands = bool(line) and not line.clearance_credited \
                and line.move_id._clearance_stands()
            expense.is_billed = stands
            expense.billed_invoice_id = line.move_id if stands else False

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
                or (exp.state == 'settled' and exp.payment_mode != 'advance')
                or exp.state == 'cancel')

    def _clearance_documents_added(self, attachments):
        """A document's arrival dates itself on the expense."""
        self._stamp_documents_received()

    def _compute_request_document_ids(self):
        self._clearance_compute_documents(
            'request_document_ids', self.REQUEST_KINDS)

    def _inverse_request_document_ids(self):
        self._clearance_adopt_documents(
            'request_document_ids', self.REQUEST_KINDS, kind='request')

    def _compute_payment_evidence_ids(self):
        self._clearance_compute_documents('payment_evidence_ids', ('payment',))

    def _compute_cash_voucher_ids(self):
        self._clearance_compute_documents('cash_voucher_ids', ('voucher',))

    def _inverse_cash_voucher_ids(self):
        self._clearance_adopt_documents(
            'cash_voucher_ids', ('voucher',), kind='voucher')

    def _compute_signed_voucher_ids(self):
        self._clearance_compute_documents('signed_voucher_ids', ('signed',))

    def _inverse_signed_voucher_ids(self):
        self._clearance_adopt_documents(
            'signed_voucher_ids', ('signed',), kind='signed')

    # The union the chatter and the justification count read is the
    # request documents and the payment evidence. The vouchers are left
    # out: a voucher is not a receipt, and it must never count as the
    # document that justifies an advance.
    DOCUMENT_KINDS = ('request', False, 'payment')

    def _compute_attachment_ids(self):
        self._clearance_compute_documents('attachment_ids', self.DOCUMENT_KINDS)

    def _inverse_attachment_ids(self):
        self._clearance_adopt_documents('attachment_ids', self.DOCUMENT_KINDS)

    def _inverse_payment_evidence_ids(self):
        self._clearance_adopt_documents(
            'payment_evidence_ids', ('payment',), kind='payment')

    def _stamp_documents_received(self):
        """The first document's arrival dates itself, once."""
        now = fields.Datetime.now()
        # sudo(): the stamp is the system recording a fact, not the
        # uploader choosing to write on the expense.
        for exp in self.sudo().exists():
            if not exp.date_documents_submitted:
                exp.date_documents_submitted = now

    @api.constrains('vendor_id', 'employee_id', 'payment_mode')
    def _check_one_counterparty(self):
        """Money goes to a vendor or to a staff member, never to both.

        Enforced here as well as greyed out in the form, because the form is
        a courtesy and the constraint is the rule.
        """
        for exp in self:
            if exp.vendor_id and exp.employee_id:
                raise ValidationError(self.env._(
                    "%s names both a vendor and an advance holder. It is one "
                    "or the other: a disbursement paid to a third party, or "
                    "cash handed to a staff member.", exp.name))
            if exp.payment_mode == 'advance' and exp.vendor_id:
                raise ValidationError(self.env._(
                    "%s is a staff advance, so it has no vendor.", exp.name))

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

    @api.depends('state')
    @api.depends_context('uid')
    def _compute_can_edit_payment(self):
        finance = self.env.su or self.env.user.has_group(FINANCE_GROUP)
        for exp in self:
            exp.can_edit_payment = (
                exp.state in REQUESTER_STATES
                or (finance and exp.state == 'approved'))

    @api.model
    def _derived_payment_mode(self, journal, employee):
        """The mode the channel and the counterparty imply."""
        if employee:
            return 'advance'
        if journal:
            # sudo: the type of a journal is not a secret, and the
            # requester keying it may not be an accounting user
            return 'cash' if journal.sudo().type == 'cash' else 'electronic'
        return False

    @api.onchange('journal_id', 'employee_id')
    def _onchange_payment_channel(self):
        """The requester picks a channel or a staff member; the mode
        follows, so nobody is asked a question whose answer they have
        just given. Finance may still set it by hand afterwards."""
        mode = self._derived_payment_mode(self.journal_id, self.employee_id)
        if mode and mode != self.payment_mode:
            self.payment_mode = mode

    @api.onchange('payment_mode')
    def _onchange_payment_mode(self):
        """One counterparty per mode: an advance has a holder, a cash or
        electronic payment has a vendor.

        The originator names the vendor when keying; Finance may then
        decide the money goes out as a staff advance. The two fields grey
        each other out, so without this the form would lock Finance
        between a vendor it cannot clear and a holder it cannot set.
        Switching mode drops the other counterparty - visibly, with a
        warning, never silently.
        """
        if self.payment_mode == 'advance' and self.vendor_id:
            dropped = self.vendor_id.display_name
            self.vendor_id = False
            return {'warning': {
                'title': self.env._("Vendor cleared"),
                'message': self.env._(
                    "%s was named as the vendor. A staff advance has a "
                    "holder instead, so the vendor has been cleared - pick "
                    "the employee who receives the money.", dropped)}}
        if self.payment_mode in ('cash', 'electronic') and self.employee_id:
            dropped = self.employee_id.display_name
            self.employee_id = False
            return {'warning': {
                'title': self.env._("Advance holder cleared"),
                'message': self.env._(
                    "%s was named as the advance holder. A cash or "
                    "electronic payment goes to a vendor instead, so the "
                    "holder has been cleared.", dropped)}}

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
        # The Clearance Administrator is every role at once (07/10/2026):
        # Finance among them, so the rule would fire on the one person
        # meant to be able to do everything.
        if user.has_group(ADMIN_GROUP):
            return
        if user.has_group(FINANCE_GROUP):
            raise UserError(self.env._(
                "Finance does not key expenses. The team that incurred the "
                "cost enters it; Finance decides how it is paid."))
        if not any(user.has_group(g) for g in ORIGINATING_GROUPS):
            raise UserError(self.env._(
                "Only the Operations, Customer Service or Transit team may "
                "enter an expense."))

    def _settlement_value_changes(self, field, value):
        """A blank sent for a blank, or a value equal to what is stored, is
        not the originator deciding how the money leaves - it is the web
        client serialising every field it shows. Only a real change is
        Finance's to make."""
        if not self:                          # create
            return bool(value)
        for rec in self:
            current = rec[field]
            if isinstance(current, models.BaseModel):
                current = current.id
            if (current or False) != (value or False):
                return True
        return False

    def _check_settlement_fields(self, vals):
        """The requester keys the channel and the counterparty while the
        expense is theirs; once approved, only Finance may change them
        (owner, 02/10/2026)."""
        if self.env.su:
            return
        touched = [f for f in SETTLEMENT_FIELDS
                   if f in vals and self._settlement_value_changes(f, vals[f])]
        if not touched or self.env.user.has_group(FINANCE_GROUP):
            return
        locked = self.filtered(lambda exp: exp.state not in REQUESTER_STATES)
        if locked:
            raise UserError(self.env._(
                "%(exp)s is approved: who is paid, through which channel "
                "and how is Finance's to change now, not the team that "
                "keyed it (%(fields)s).",
                exp=", ".join(locked.mapped('name')),
                fields=", ".join(self._fields[f].string for f in touched)))

    @api.model
    def _fill_payment_mode(self, vals, current=None):
        """Derive the mode from what was keyed, unless it was keyed too."""
        if vals.get('payment_mode') or not (
                'journal_id' in vals or 'employee_id' in vals):
            return vals
        journal = self.env['account.journal'].browse(
            vals['journal_id'] if 'journal_id' in vals
            else (current.journal_id.id if current else False))
        employee = self.env['hr.employee'].browse(
            vals['employee_id'] if 'employee_id' in vals
            else (current.employee_id.id if current else False))
        mode = self._derived_payment_mode(journal, employee)
        if mode and (current is None or current.payment_mode != mode):
            vals['payment_mode'] = mode
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        team = self._team_of_current_user()
        if team:
            for vals in vals_list:
                vals.setdefault('originating_team', team)
        self._check_originating_team()
        for vals in vals_list:
            self._check_settlement_fields(vals)
            self._fill_payment_mode(vals)
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

    # Which queue a state lands the expense in. Read in write() rather
    # than bolted on to each action: there are eight actions and a ninth
    # will be written one day, and a queue nobody is told about is worse
    # than no queue.
    NOTIFY_KIND = {
        'submitted': 'expense_approve',
        'approved': 'settlement_key',
        'settlement_submitted': 'settlement_approve',
        'justification_submitted': 'justification_approve',
        'justification_ops_approved': 'justification_finance',
    }

    def write(self, vals):
        self._check_settlement_fields(vals)
        if len(self) == 1:
            vals = self._fill_payment_mode(dict(vals), current=self)
        res = super().write(vals)
        if 'state' in vals:
            for expense in self:
                expense._notify_landed()
        return res

    def _notify_landed(self):
        """Tell whoever the expense has just landed on."""
        self.ensure_one()
        Task = self.env['clearance.task']
        kind = self.NOTIFY_KIND.get(self.state)
        if kind == 'expense_approve' and self.originating_team:
            # the head of the service that keyed it, and nobody else
            head = self.env.ref(HEAD_OF_TEAM[self.originating_team],
                                raise_if_not_found=False)
            users = self.env['res.users'].sudo().search([
                ('all_group_ids', 'in', head.ids), ('share', '=', False),
                ('company_ids', 'in', self.company_id.ids)]) \
                if head else self.env['res.users']
            Task._notify_assignment(kind, self, users=users,
                                    detail=self.description)
            return
        if kind:
            Task._notify_assignment(kind, self, detail=self.description)
            return
        if self.state == 'settlement_approved':
            # the money leaves through the till or through the bank, and
            # they are different people
            kind = ('disburse_cash' if self.journal_id.type == 'cash'
                    else 'disburse_bank')
            Task._notify_assignment(kind, self, detail=self.description)
            return
        if (self.state == 'settled' and self.payment_mode == 'advance'
                and self.justification_required):
            # an advance is one person's debt, not a department's queue
            holder = self.employee_id.user_id
            if holder:
                Task._notify_assignment(
                    'advance_justify', self, users=holder,
                    detail=self.description)

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

    def _vendor_payable_account(self):
        """The payable account the selected vendor is auxiliarised to.

        Odoo carries it per partner (`property_account_payable_id`), which
        for Elimelec resolves to 401100 Suppliers unless a vendor has been
        given one of their own. Advances have no vendor, and a vendor with
        no payable account falls back to a plain two-line entry rather than
        failing the disbursement.
        """
        self.ensure_one()
        if self.payment_mode == 'advance' or not self.vendor_id:
            return False
        return self.vendor_id.property_account_payable_id or False

    def _payment_credit_account(self):
        """The account the money leaves from when a disbursement is paid.

        A till is credited directly: the cash is gone the moment it is
        handed over and no statement will ever confirm it. Every other
        channel - bank, Mobile Money, Maviance - is credited to that
        journal's OWN holding account, its "Outstanding Payments" account
        on the outgoing payment method (owner spec 09/10/2026). The bank
        account itself moves only when the statement line is matched
        against it, so the books agree with the bank line by line and the
        holding account's balance is what has been paid but not yet
        cleared. Before this, the settlement credited the bank account
        and the imported statement credited it a second time.

        One holding account per journal, because the owner wants each
        bank's uncleared payments on their own line; a shared one is
        refused rather than quietly accepted.
        """
        self.ensure_one()
        journal = self.journal_id
        if journal.type == 'cash':
            if not journal.default_account_id:
                raise UserError(self.env._(
                    "Journal %s has no default account.", journal.name))
            return journal.default_account_id
        how = self.env._(
            "Set it in Accounting -> Configuration -> Journals -> %(journal)s "
            "-> Outgoing Payments -> Outstanding Payments account: an "
            "account of its own, with Allow Reconciliation ticked.",
            journal=journal.name)
        # Read off the lines rather than through Odoo's own getter, which
        # browses an empty id for a method with no account set.
        holding = journal.sudo().outbound_payment_method_line_ids.payment_account_id
        if len(holding) != 1:
            raise UserError(self.env._(
                "%(exp)s cannot be paid through %(journal)s: the journal "
                "needs exactly one holding account for payments not yet "
                "through the bank, and it has %(count)s. %(how)s",
                exp=self.name, journal=journal.name, count=len(holding),
                how=how))
        if holding == journal.default_account_id or not holding.reconcile:
            raise UserError(self.env._(
                "%(exp)s cannot be paid through %(journal)s: its holding "
                "account %(account)s must be reconcilable and must not be "
                "the bank account itself, or the statement has nothing to "
                "clear. %(how)s",
                exp=self.name, journal=journal.name,
                account=holding.display_name, how=how))
        shared = self.env['account.journal'].sudo().search([
            ('company_id', '=', journal.company_id.id),
            ('id', '!=', journal.id),
            ('outbound_payment_method_line_ids.payment_account_id', '=', holding.id),
        ])
        if shared:
            raise UserError(self.env._(
                "%(exp)s cannot be paid through %(journal)s: its holding "
                "account %(account)s is also used by %(others)s. Each bank "
                "keeps its own, so its uncleared payments read on their own "
                "line. %(how)s",
                exp=self.name, journal=journal.name,
                account=holding.display_name,
                others=", ".join(shared.mapped('name')), how=how))
        return holding

    def _oop_accrual_account(self):
        """The 471xx a disbursement waits on between approval and payment.

        Empty means the company has not asked for the two-stage treatment
        and everything behaves as it did before.
        """
        self.ensure_one()
        return self.company_id.clearance_oop_payable_account_id

    def _accrual_postings(self, account, payable):
        """Dr Débours à engager / Cr the third party."""
        self.ensure_one()
        return [(account, self.vendor_id, self.amount, 0.0),
                (payable, self.vendor_id, 0.0, self.amount)]

    def _post_accrual(self):
        """Recognise what is owed the moment it is owed.

        The owner's rule of 01/10/2026: a disbursement is a debt from the
        moment it is approved and the third party is named, not from the
        moment the money leaves. Until it is paid it sits on its own 471
        account - débours À ENGAGER - against the vendor's payable;
        paying it moves that debit across to débours ENGAGÉS, which is
        what the client is billed from.

        It is posted here, at the settlement submission, and not at the
        team's own submission as the instruction read - because since
        19/09/2026 the third party is Finance's to name, and until they
        name it there is nobody to credit. Move this call to
        action_submit if that decision is ever reversed.

        An advance to a member of staff is untouched: it has no vendor,
        it is not owed to anybody, and it already has its own two-step
        treatment through 421101.
        """
        self.ensure_one()
        account = self._oop_accrual_account()
        payable = self._vendor_payable_account()
        if not account or not payable or self.accrual_move_id:
            return
        analytic = self._analytic_distribution()
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self._accrual_journal().id,
            'logistics_file_id': self.file_id.id,
            'date': fields.Date.context_today(self),
            'ref': self.env._("%(exp)s — %(label)s — à engager",
                              exp=self.name, label=self._ledger_label()),
            'line_ids': [
                fields.Command.create({
                    'name': self._ledger_label(),
                    'account_id': acc.id,
                    'partner_id': who.id if who else False,
                    'debit': debit, 'credit': credit,
                    'analytic_distribution': analytic,
                })
                for acc, who, debit, credit
                in self._accrual_postings(account, payable)
            ],
        })
        move.action_post()
        self.accrual_move_id = move.id
        self.message_post(body=self.env._(
            "%(amount)s recognised as owed to %(vendor)s: debited to "
            "%(account)s until it is paid.",
            amount=self.amount, vendor=self.vendor_id.display_name,
            account=account.display_name))

    def _accrual_journal(self):
        """The miscellaneous journal: no money moves, so it is not the
        till's or the bank's."""
        self.ensure_one()
        journal = self.company_id.clearance_misc_journal_id
        if not journal:
            journal = self.env['account.journal'].search(
                [('type', '=', 'general'),
                 ('company_id', '=', self.company_id.id)], limit=1)
        if not journal:
            raise UserError(self.env._(
                "Company %s has no miscellaneous journal to recognise a "
                "disbursement in.", self.company_id.name))
        return journal

    def _reverse_accrual(self, why):
        """Unrecognise it: the same entry, the other way round."""
        self.ensure_one()
        source = self.accrual_move_id
        if not source or source.state != 'posted':
            return
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': source.journal_id.id,
            'logistics_file_id': self.file_id.id,
            'date': fields.Date.context_today(self),
            'ref': self.env._("Reversal of %s", source.name),
            'line_ids': [
                fields.Command.create({
                    'name': line.name,
                    'account_id': line.account_id.id,
                    'partner_id': line.partner_id.id or False,
                    'debit': line.credit, 'credit': line.debit,
                    'analytic_distribution': line.analytic_distribution,
                })
                for line in source.line_ids
            ],
        })
        move.action_post()
        self.message_post(body=self.env._(
            "What was recognised as owed has been reversed (%(move)s): "
            "%(why)s", move=move.name, why=why))
        return move

    def action_open_settle_wizard(self):
        """Disburse / Pay opens a dialog that asks for the evidence."""
        self.ensure_one()
        self._check_disburser()
        if self.state != 'settlement_approved':
            raise UserError(self.env._(
                "The settlement of %s has not been approved by the "
                "Head of Service Finance.", self.name))
        # Before the evidence is attached, not after: Treasury should not
        # scan a transfer advice only to be told the journal is not set up.
        self._payment_credit_account()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'elite_clearance.action_expense_settle_wizard')
        action['context'] = {'default_expense_id': self.id}
        return action

    # --- the petty-cash voucher (owner 10/10/2026) -----------------------
    def _issue_cash_voucher(self):
        """Print the voucher and keep it on the disbursement.

        Rendered once, at Disburse / Pay, so what the cashier hands over
        to be signed is what the system recorded at that moment. Under
        --test-enable Odoo renders the HTML instead of calling
        wkhtmltopdf, which is why this can run inside a TransactionCase.
        """
        Report = self.env['ir.actions.report'].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        for exp in self:
            if exp.cash_voucher_ids or exp.is_legacy:
                continue
            content, kind = Report._render_qweb_pdf(
                'elite_clearance.action_report_cash_voucher', res_ids=exp.ids)
            if isinstance(content, str):
                content = content.encode()
            pdf = kind == 'pdf'
            Attachment.create({
                'name': "Avance frais %s.%s" % (
                    (exp.name or "").replace('/', '-'), 'pdf' if pdf else 'html'),
                'raw': content,
                'mimetype': 'application/pdf' if pdf else 'text/html',
                'res_model': exp._name,
                'res_id': exp.id,
                'clearance_kind': 'voucher',
            })
        self.invalidate_recordset(['cash_voucher_ids'])

    def action_print_cash_voucher(self):
        """The same document, printed again."""
        self.ensure_one()
        if self.journal_id.type != 'cash':
            raise UserError(self.env._(
                "%s is not paid from a till; a cash voucher is printed for "
                "cash only.", self.name))
        return self.env.ref(
            'elite_clearance.action_report_cash_voucher').report_action(self)

    def _voucher_stamp(self, when):
        """A date and time in the reader's time zone, or now."""
        if when is None:
            when = fields.Datetime.now()
        if not when:
            return ""
        return fields.Datetime.context_timestamp(
            self, when).strftime('%d/%m/%Y %H:%M')

    def _voucher_client_name(self):
        self.ensure_one()
        partner = self.file_id.partner_id
        return partner.clearance_invoice_name or partner.name or ""

    def _voucher_approvals(self):
        """Every approval the disbursement went through: role, name, when."""
        self.ensure_one()
        teams = dict(self._fields['originating_team'].selection)
        team = teams.get(self.originating_team)
        head = ("Chef du service demandeur (%s)" % team if team
                else "Chef du service demandeur")
        steps = [
            (head, self.approved_by_id, self.date_approved),
            ("Agent Finance", self.settlement_submitted_by_id,
             self.date_settlement_submitted),
            ("Chef du service Finance", self.settlement_approved_by_id,
             self.date_settlement_approved),
            ("Caissier", self.settled_by_id, self.date_settled),
        ]
        return [{'role': role, 'name': user.name or "",
                 'date': self._voucher_stamp(when) if when else ""}
                for role, user, when in steps]

    def _unsigned_cash_vouchers(self):
        """The cash payments whose signed voucher has not come back."""
        return self.filtered(
            lambda e: e.settlement_move_id and e.journal_id.type == 'cash'
            and not e.is_legacy and not e.signed_voucher_ids)

    def action_send_payment_evidence(self):
        """Customer Service sends the third party the proof it was paid.

        Opens Odoo's composer on the disbursement with the vendor as
        recipient and the payment evidence attached; sending posts the
        message in the chatter and stamps when and by whom
        (`message_post`, below).
        """
        self.ensure_one()
        if not self.env.user.has_group(
                'elite_clearance.group_clearance_customer_service'):
            raise UserError(self.env._(
                "Payment evidence is sent to the third party by Customer "
                "Service."))
        if not self.vendor_id:
            raise UserError(self.env._(
                "%s names no third party to send the evidence to.",
                self.name))
        if not self.payment_evidence_ids:
            raise UserError(self.env._(
                "%s carries no payment evidence yet.", self.name))
        if not self.vendor_id.email:
            raise UserError(self.env._(
                "%(vendor)s has no e-mail address. Add one on the contact "
                "and try again.", vendor=self.vendor_id.display_name))
        template = self.env.ref(
            'elite_clearance.mail_template_payment_evidence',
            raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Send Payment Evidence"),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': self._name,
                'default_res_ids': self.ids,
                'default_composition_mode': 'comment',
                'default_template_id': template.id if template else False,
                'default_partner_ids': [(6, 0, self.vendor_id.ids)],
                'default_attachment_ids': [(6, 0, self.payment_evidence_ids.ids)],
                'force_email': True,
                'clearance_payment_evidence': True,
            },
        }

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        if self.env.context.get('clearance_payment_evidence'):
            # the system recording a fact, not the sender writing on
            # a settled disbursement
            self.sudo().write({
                'payment_evidence_sent_date': fields.Datetime.now(),
                'payment_evidence_sent_by_id': self.env.user.id})
        return message

    def _ledger_label(self):
        """What every journal item of this disbursement is called.

        "<expense category> / <file number>" (owner 10/10/2026) - the
        requester's free text used to be the label, and a ledger that
        reads "2 days demurrage, see Paul" is a ledger nobody can sort.
        The expense's own reference stays in the entry's Reference.
        """
        self.ensure_one()
        return "%s / %s" % (self.category_id.name or "", self.file_id.name or "")

    def _check_disburser(self):
        """Cash leaves through the Cashier, bank money through Treasury."""
        for exp in self:
            kind = 'cash_disburse' if exp.journal_id.type == 'cash' else 'bank_disburse'
            exp.company_id._clearance_check_approver(kind)

    @api.model
    def _team_of_current_user(self):
        """The originating team the current user belongs to, or False."""
        if self.env.su:
            return False
        user = self.env.user
        # An administrator is in every group; they configure, they do
        # not operate, and an expense they key belongs to no team. The
        # Clearance Administrator is every team at once, so the same.
        if user.has_group('base.group_system') or user.has_group(ADMIN_GROUP):
            return False
        for group, team in TEAM_OF_GROUP.items():
            if user.has_group(group):
                return team
        return False

    def _check_manager(self):
        """The head of the service that keyed it approves it.

        An explicit approver list on the company still wins, as it does
        for every checkpoint. Without one, the Head of Service Operations
        signs Operations' costs, the Head of Customer Service theirs, the
        Head of Service Transit theirs - and a cost that belongs to no
        team (keyed by an administrator or imported) may be signed by any
        of the three, which is what the rule was before 02/10/2026.
        """
        for exp in self:
            company = exp.company_id
            if company.clearance_expense_approver_ids:
                company._clearance_check_approver('expense')
                continue
            head = HEAD_OF_TEAM.get(exp.originating_team)
            if not head:
                company._clearance_check_approver('expense')
                continue
            if not self.env.user.has_group(head):
                labels = dict(exp._fields['originating_team'].selection)
                raise UserError(self.env._(
                    "%(exp)s was keyed by %(team)s, so its head approves "
                    "it - not another service's.",
                    exp=exp.name, team=labels[exp.originating_team]))

    # ------------------------------------------------------------------
    # workflow
    # ------------------------------------------------------------------
    def action_open_expense(self):
        """The workflow lives on the record's own page, not in the dialog."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'logistics.expense',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_submit(self):
        for exp in self:
            if exp.state != 'draft':
                raise UserError(self.env._("%s is not in draft.", exp.name))
            exp.write({'state': 'submitted',
                       'date_submitted': fields.Datetime.now()})

    def action_approve(self):
        self._check_manager()
        for exp in self:
            if exp.state != 'submitted':
                raise UserError(self.env._(
                    "%s has not been submitted for approval.", exp.name))
            exp.write({'state': 'approved',
                       'date_approved': fields.Datetime.now(),
                       'approved_by_id': self.env.user.id})

    def action_refuse(self):
        self._check_manager()
        for exp in self:
            if exp.settlement_move_id:
                raise UserError(self.env._(
                    "%s has been paid. Reverse the settlement entry from "
                    "Accounting before refusing it.", exp.name))
            exp._reverse_accrual(self.env._("the disbursement was refused"))
        self.write({'state': 'cancel'})
        for exp in self:
            exp._clearance_post_rejection(
                self.env._("Disbursement refused by %s.", self.env.user.name),
                requesters=exp.create_uid)

    def action_submit_settlement(self):
        """Finance has confirmed - or corrected - how it is paid; hand it
        to the Head of Service Finance."""
        for exp in self:
            if exp.state != 'approved':
                raise UserError(self.env._(
                    "%s is not approved by its team manager yet.", exp.name))
            if not self.env.su and not self.env.user.has_group(FINANCE_GROUP):
                raise UserError(self.env._(
                    "Only Finance sends an expense on for payment."))
            if not exp.payment_mode:
                mode = exp._derived_payment_mode(exp.journal_id, exp.employee_id)
                if mode:
                    exp.payment_mode = mode
            missing = []
            if not exp.payment_mode:
                missing.append(exp._fields['payment_mode'].string)
            if not exp.journal_id:
                missing.append(exp._fields['journal_id'].string)
            if exp.payment_mode in ('cash', 'electronic') and not exp.vendor_id:
                missing.append(exp._fields['vendor_id'].string)
            if exp.payment_mode == 'advance' and not exp.employee_id:
                missing.append(exp._fields['employee_id'].string)
            if missing:
                raise UserError(self.env._(
                    "Key %(what)s on %(exp)s before sending it to the "
                    "Head of Service Finance.", what=", ".join(missing), exp=exp.name))
            exp.write({'state': 'settlement_submitted',
                       'date_settlement_submitted': fields.Datetime.now(),
                       'settlement_submitted_by_id': self.env.user.id})
            exp.message_post(body=self.env._(
                "Settlement sent to the Head of Service Finance for approval."))
            # The third party is named and the expense is approved: this
            # is the first moment the debt can be recognised against
            # somebody (owner spec 01/10/2026).
            exp._post_accrual()

    def action_return_settlement(self):
        """The Head of Service Finance sends it back to Finance to correct."""
        for exp in self:
            exp.company_id._clearance_check_approver('settlement')
            if exp.state != 'settlement_submitted':
                raise UserError(self.env._(
                    "%s is not awaiting the Head of Service Finance.", exp.name))
            exp.state = 'approved'
            exp._clearance_post_rejection(self.env._(
                "Settlement returned to Finance by the Head of Service Finance."),
                requesters=exp._clearance_users('settlement_key'))

    def action_approve_settlement(self):
        """The Head of Service Finance signs how Finance proposes to pay."""
        for exp in self:
            exp.company_id._clearance_check_approver('settlement')
            if exp.state != 'settlement_submitted':
                raise UserError(self.env._(
                    "%s has not been sent to the Head of Service Finance by "
                    "Finance yet.", exp.name))
            if not exp.payment_mode or not exp.journal_id:
                raise UserError(self.env._(
                    "Finance must set the payment mode and the settlement "
                    "journal on %s before it can be approved.", exp.name))
            exp.write({'state': 'settlement_approved',
                       'date_settlement_approved': fields.Datetime.now(),
                       'settlement_approved_by_id': self.env.user.id})
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
                    "Head of Service Finance.", exp.name))
            if not exp.journal_id:
                raise UserError(self.env._(
                    "Choose the settlement journal on %s — Cash, Bank, "
                    "Mobile Money or Maviance.", exp.name))
            # No evidence, no payment (owner, 01/10/2026). The button
            # opens a dialog that asks for it; this is the rule the dialog
            # enforces, so a call from anywhere else meets it too. su is
            # exempt: fixtures and the importer are not cashiers. A TILL
            # is exempt as well (owner 10/10/2026): its evidence is the
            # voucher this very action prints, signed by whoever takes
            # the cash and uploaded afterwards - the ops-close gate holds
            # the file until it is.
            if (not self.env.su and not exp.payment_evidence_ids
                    and exp.journal_id.type != 'cash'):
                raise UserError(self.env._(
                    "Attach the payment evidence for %s - the receipt, "
                    "the transfer advice or the mobile-money confirmation "
                    "- before it is paid out.", exp.name))
            direct = exp.payment_mode != 'advance'
            # A NON-JUSTIFIABLE advance is spent the moment it is handed
            # over: no document will ever exist for it, so it never sits
            # on 421101 as the holder's debt and it is billable at once
            # (owner spec 15/09/2026). The holder still goes on the line,
            # because who was given the money is worth knowing.
            if direct or not exp.justification_required:
                debit_account = exp._get_company_account(
                    'clearance_oop_account_id', "Out-of-Pocket Expenses account")
                partner = (exp.vendor_id if direct
                           else exp.employee_id._clearance_auxiliary_partner())
            else:
                debit_account = exp._get_company_account(
                    'clearance_advance_account_id', "Employee Advances account")
                # The auxiliary on 421101. Created on demand rather than
                # refused, because hr only makes the work contact as a side
                # effect of writing a work e-mail or phone.
                partner = exp.employee_id._clearance_auxiliary_partner()
            # Tagged like every other line: the file number goes on
            # everything that reaches the ledger, including an advance
            # sitting on 421101 before it is justified.
            analytic = exp._analytic_distribution()
            credit_account = exp._payment_credit_account()

            # (account, partner, debit, credit)
            payable = exp._vendor_payable_account()
            if exp.accrual_move_id:
                # The debt was recognised when the disbursement was
                # approved, so paying it does two things at once (owner
                # spec 01/10/2026): it clears the third party against the
                # money going out, and it moves the debit from "to
                # engage" across to "engaged", which is the account
                # billing recharges from. Both halves in one entry,
                # because they are one event.
                accrual = exp._oop_accrual_account()
                postings = [
                    (payable, exp.vendor_id, exp.amount, 0.0),
                    (credit_account, exp.vendor_id, 0.0, exp.amount),
                    (debit_account, exp.vendor_id, exp.amount, 0.0),
                    (accrual, exp.vendor_id, 0.0, exp.amount),
                ]
            else:
                postings = [(debit_account, partner, exp.amount, 0.0)]
                if payable:
                    # The vendor's own payable account, with the vendor as
                    # the auxiliary, so every third party has a ledger of
                    # what was charged to them and what was paid.
                    # Recognised and settled in the same move: 401100 nets
                    # to nil for this expense and the money still leaves
                    # today.
                    postings.append((payable, exp.vendor_id, 0.0, exp.amount))
                    postings.append((payable, exp.vendor_id, exp.amount, 0.0))
                postings.append((credit_account, partner, 0.0, exp.amount))

            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': exp.journal_id.id,
                'logistics_file_id': exp.file_id.id,
                'date': fields.Date.context_today(exp),
                'ref': self.env._("%(exp)s — %(label)s",
                                  exp=exp.name, label=exp._ledger_label()),
                'line_ids': [
                    fields.Command.create({
                        'name': exp._ledger_label(),
                        'account_id': account.id,
                        'partner_id': counterparty.id if counterparty else False,
                        'debit': debit, 'credit': credit,
                        'analytic_distribution': analytic,
                    })
                    for account, counterparty, debit, credit in postings
                ],
            })
            move.action_post()
            exp.write({
                'settlement_move_id': move.id,
                'state': 'settled',
                'date_settled': fields.Datetime.now(),
                'settled_by_id': self.env.user.id,
            })
            if exp.journal_id.type == 'cash':
                exp._issue_cash_voucher()

    def action_submit_justification(self):
        """The receipts go up for review.

        Sent by Finance, or by the staff member holding the advance:
        it is their debt until it is justified, the queue shows it to
        them as theirs to clear (owner, 11/09/2026), and a queue whose
        row cannot be acted on is worse than no queue at all.

        Attaching a receipt is not the same as the receipt being
        accepted. The reclassification that makes an advance billable is
        an operational judgement AND a movement between two accounts, so
        it is approved twice - Operations, then the Head of Service Finance.
        """
        for exp in self:
            if not exp.justification_required:
                raise UserError(self.env._(
                    "%(exp)s is a %(cat)s cost: there is no document to "
                    "produce for it, and none is waited on. It was "
                    "charged to the engaged-disbursements account when it "
                    "was paid.",
                    exp=exp.name, cat=exp.category_id.name))
            if not exp._is_held_by_current_user():
                exp._check_finance()
        for exp in self:
            if exp.state != 'settled' or exp.payment_mode != 'advance':
                raise UserError(self.env._(
                    "%s is not a settled cash advance.", exp.name))
            attachments = self.env['ir.attachment'].search_count([
                ('res_model', '=', self._name), ('res_id', '=', exp.id)])
            if not attachments:
                raise UserError(self.env._(
                    "Attach the supporting documents to %s before sending "
                    "the justification for approval.", exp.name))
            exp.write({'state': 'justification_submitted',
                       'date_justification_submitted': fields.Datetime.now()})
            exp.message_post(body=self.env._(
                "Justification submitted with %(count)s supporting "
                "document(s), for the Head of Service Operations and then the "
                "Head of Service Finance to review.", count=attachments))

    def _is_engaged(self):
        """Has this cost reached the engaged-disbursements account?

        Justified, or paid direct - and since 15/09/2026 a settled advance
        for a NON-JUSTIFIABLE category too, because that one went straight
        to 47xx when it was paid and there is nothing further to wait for.
        """
        self.ensure_one()
        if self.state == 'justified':
            return True
        if self.state != 'settled':
            return False
        return self.payment_mode != 'advance' or not self.justification_required

    def _is_held_by_current_user(self):
        """The advance stands against this person, so it is theirs to
        clear."""
        self.ensure_one()
        holder = self.employee_id.user_id
        return bool(holder) and holder == self.env.user

    def action_refuse_justification(self):
        """The documents do not support the advance; back to Finance."""
        for exp in self:
            if exp.state == 'justification_ops_approved':
                exp.company_id._clearance_check_approver('justification_finance')
            elif exp.state == 'justification_submitted':
                exp.company_id._clearance_check_approver('justification')
            else:
                raise UserError(self.env._(
                    "No justification is awaiting approval on %s.", exp.name))
            exp.write({'state': 'settled',
                       'date_justification_submitted': False})
            exp._clearance_post_rejection(self.env._(
                "Justification refused: the advance stays on 421101 against "
                "the holder and is not billable."),
                requesters=(exp.employee_id.user_id
                            | exp._clearance_users('settlement_key')))

    def action_justify(self):
        """The Head of Service Operations accepts the documents as evidence of
        what the money was spent on.

        It does not yet move anything: the reclassification is a
        movement between two accounts, so the Head of Service Finance signs it
        too (owner, 11/09/2026).
        """
        for exp in self:
            exp.company_id._clearance_check_approver('justification')
            if exp.state != 'justification_submitted':
                raise UserError(self.env._(
                    "%s has not been submitted for justification approval.",
                    exp.name))
            exp.write({'state': 'justification_ops_approved'})
            exp.message_post(body=self.env._(
                "Justification accepted by Operations. It now awaits the "
                "Head of Service Finance, who signs the reclassification."))

    def action_justify_finance(self):
        """The Head of Service Finance signs it; the advance is reclassified from
        421101 to the engaged account and becomes billable."""
        for exp in self:
            exp.company_id._clearance_check_approver('justification_finance')
            if exp.state != 'justification_ops_approved':
                raise UserError(self.env._(
                    "%s has not been accepted by Operations yet.", exp.name))
            # The decision is the Head of Service Operations's; the entry that
            # follows is the system's consequence of it. They hold the
            # operational authority, not accounting rights, so the
            # reclassification is written under sudo - the same reason the
            # file's analytic account is created that way.
            booking = exp.sudo()
            oop = booking._get_company_account(
                'clearance_oop_account_id', "Out-of-Pocket Expenses account")
            adv = booking._get_company_account(
                'clearance_advance_account_id', "Employee Advances account")
            journal = booking.company_id.clearance_misc_journal_id
            if not journal:
                journal = booking.env['account.journal'].search([
                    ('type', '=', 'general'),
                    ('company_id', '=', exp.company_id.id)], limit=1)
            if not journal:
                raise UserError(self.env._(
                    "Configure the Clearance Miscellaneous Journal in "
                    "Settings."))
            partner = exp.employee_id._clearance_auxiliary_partner()
            move = booking.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'logistics_file_id': exp.file_id.id,
                'date': fields.Date.context_today(exp),
                'ref': self.env._("Justification %(exp)s — %(label)s",
                                  exp=exp.name, label=exp._ledger_label()),
                'line_ids': [
                    fields.Command.create({
                        'name': exp._ledger_label(),
                        'account_id': oop.id,
                        'partner_id': exp.vendor_id.id or False,
                        'debit': exp.amount, 'credit': 0.0,
                        'analytic_distribution': exp._analytic_distribution(),
                    }),
                    fields.Command.create({
                        'name': exp._ledger_label(),
                        'account_id': adv.id,
                        'partner_id': partner.id if partner else False,
                        'debit': 0.0, 'credit': exp.amount,
                    }),
                ],
            })
            move.action_post()
            booking.write({'justification_move_id': move.id, 'state': 'justified',
                           'date_justified': fields.Datetime.now()})
            exp.message_post(body=self.env._(
                "Advance justified by Operations and the Head of Service Finance: "
                "%(amount)s reclassified from 421101 (held by %(who)s) to "
                "the engaged disbursements account. It is now billable.",
                amount=exp.amount, who=exp.employee_id.name))

    def action_reset_to_draft(self):
        for exp in self:
            if exp.state in ('settlement_submitted', 'settlement_approved'):
                raise UserError(self.env._(
                    "%s is with the Head of Service Finance or already approved for "
                    "settlement. Have it returned first.", exp.name))
            if exp.settlement_move_id or exp.accrual_move_id:
                raise UserError(self.env._(
                    "%s already has a journal entry against it. Refuse it "
                    "instead - that reverses what was recognised - or "
                    "reverse the entry from Accounting first.", exp.name))
            exp.state = 'draft'
