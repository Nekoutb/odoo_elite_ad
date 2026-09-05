from odoo import fields, models
from odoo.exceptions import UserError

# Every approval checkpoint in the module resolves through this table:
#   kind -> (company field holding the explicit approver list,
#            fallback security group when that list is empty,
#            wording used in the refusal message)
APPROVAL_KINDS = {
    'waiver': ("clearance_waiver_approver_ids",
               ('elite_clearance.group_clearance_manager',),
               "approve documentation waivers"),
    # An expense is approved by the manager of ANY originating team, not by
    # the general manager and never by Finance.
    'expense': ("clearance_expense_approver_ids",
                ('elite_clearance.group_clearance_ops_manager',
                 'elite_clearance.group_clearance_customer_service_manager',
                 'elite_clearance.group_clearance_transit_manager'),
                "approve expenses before disbursement"),
    # Finance proposes how an expense is paid; the Finance Manager signs it.
    'settlement': ("clearance_settlement_approver_ids",
                   ('elite_clearance.group_clearance_finance_manager',),
                   "approve the settlement method of an expense"),
    'finance': ("clearance_finance_approver_ids",
                ('elite_clearance.group_clearance_finance',),
                "settle and justify disbursements"),
    'billing': ("clearance_billing_approver_ids",
                ('elite_clearance.group_clearance_billing',),
                "approve billing and completion"),
    # Billing proposes a new revenue line; Operations decides whether the
    # company charges for it at all.
    'billing_service': ("clearance_billing_service_approver_ids",
                        ('elite_clearance.group_clearance_ops_manager',),
                        "approve a new billable service"),
    # Finance keys the settlement, the Finance Manager signs it, then the
    # money leaves through whoever holds the till or the bank.
    'cash_disburse': ("clearance_cashier_approver_ids",
                      ('elite_clearance.group_clearance_cashier',),
                      "disburse cash from a till"),
    'bank_disburse': ("clearance_treasury_approver_ids",
                      ('elite_clearance.group_clearance_treasury',),
                      "pay from a bank or mobile-money account"),
    # An imported file is history; billing it again is an exception the
    # Operations Manager signs after review.
    'reopen_imported': ("clearance_reopen_imported_approver_ids",
                        ('elite_clearance.group_clearance_ops_manager',),
                        "approve reopening an imported file"),
    # Reclassifying an advance to the billable account is an operational
    # judgement about whether the documents really support it.
    'justification': ("clearance_justification_approver_ids",
                      ('elite_clearance.group_clearance_ops_manager',),
                      "approve the justification of a staff advance"),
    # Recharging the client at anything other than cost. Above cost needs
    # Operations; below cost needs Operations AND the Finance Manager,
    # because the company is giving margin away.
    'recharge_ops': ("clearance_recharge_ops_approver_ids",
                     ('elite_clearance.group_clearance_ops_manager',),
                     "approve a change to the disbursement recharge"),
    'recharge_gm': ("clearance_recharge_gm_approver_ids",
                    ('elite_clearance.group_clearance_manager',),
                    "approve recharging the client BELOW cost"),
    'ops_close': ("clearance_ops_close_approver_ids",
                  ('elite_clearance.group_clearance_ops_manager',),
                  "close a file for operations"),
    'advance_waiver': ("clearance_advance_waiver_approver_ids",
                       ('elite_clearance.group_clearance_ops_manager',),
                       "waive unjustified staff advances so a file can be "
                       "billed"),
}


class ResCompany(models.Model):
    _inherit = 'res.company'

    clearance_oop_account_id = fields.Many2one(
        'account.account', string="Engaged Disbursements Account (47xx)",
        help="47xx Débours engagés. A disbursement reaches this account only "
             "once it is supported: paid direct, or advanced to staff and "
             "then justified with documents. The client invoice recharges "
             "this account at cost, which clears it. Nothing outside this "
             "account is ever billed.",
    )
    clearance_advance_account_id = fields.Many2one(
        'account.account', string="Staff Advances Account (421101)",
        help="421101 Personnel débours avancés. Money handed to a staff "
             "member sits here, against that person as auxiliary, until "
             "they produce the supporting documents. It is their debt, not "
             "the client's, and it is never invoiced from here.",
    )
    clearance_fee_account_id = fields.Many2one(
        'account.account', string="Fee Income Account (default)",
        help="Fallback income account for fee lines. Used only where the "
             "commission and service-fee accounts below are left empty.",
    )
    clearance_oop_undercharge_account_id = fields.Many2one(
        'account.account', string="Disbursement Undercharge Account",
        help="Expense account carrying what was disbursed for the client "
             "but deliberately not recharged. 47xx still clears in full; "
             "the shortfall is booked here as a cost of the decision.",
    )
    clearance_oop_overcharge_account_id = fields.Many2one(
        'account.account', string="Disbursement Overcharge Account",
        help="Income account carrying anything charged above what was "
             "actually disbursed. Kept apart from the commission and the "
             "service fee so the margin taken on débours is visible.",
    )
    clearance_commission_account_id = fields.Many2one(
        'account.account', string="Commission Income Account (706x)",
        help="Where the clearance commission is credited - the percentage "
             "of the out-of-pocket total set on the service type. A "
             "subdivision of 706 Services vendus.",
    )
    clearance_service_fee_account_id = fields.Many2one(
        'account.account', string="Service Fee Income Account (706x)",
        help="Where the customs service fee keyed from the declaration is "
             "credited. Also a subdivision of 706, kept apart from the "
             "commission so the two revenue streams are reportable.",
    )
    # --- what the printed invoice says -----------------------------
    # ONLY the strings Odoo has nowhere else to keep. The logo, NIU, RC,
    # address and bank accounts are read from the company and its bank
    # accounts, never copied here: a second copy would keep printing the
    # old account number after somebody updated the real one.
    clearance_invoice_title = fields.Char(
        string="Invoice Title", default="Facture doit N°",
        help="Printed above the invoice number.")
    clearance_invoice_vat_label = fields.Char(
        string="VAT Line Label", default="TVA SUR PRESTATIONS",
        help="The rate is appended automatically from the tax actually "
             "charged, so this is the wording only.")
    clearance_invoice_payment_terms = fields.Char(
        string="Payment Conditions", default="As per agreement with customer",
        help="Printed in the bank block when the invoice carries no payment "
             "term of its own.")
    clearance_invoice_complaint_days = fields.Integer(
        string="Complaints Window (days)", default=15,
        help="Printed as 'Max period for complaints regarding invoices'.")
    clearance_invoice_bank_ids = fields.Many2many(
        'res.partner.bank', 'res_company_clearance_invoice_bank_rel',
        'company_id', 'bank_id', string="Bank Accounts on the Invoice",
        help="Which accounts print, and in what order. Empty prints the "
             "first two the company has.")

    clearance_service_tax_ids = fields.Many2many(
        'account.tax', 'res_company_clearance_service_tax_rel',
        'company_id', 'tax_id', string="VAT on Service Fees",
        domain="[('type_tax_use', '=', 'sale')]",
        help="Applied to commission, customs fees and any other service "
             "line on a clearance invoice. Disbursements are NEVER taxed "
             "here: they are the client's own liability paid on their "
             "behalf, outside the scope of VAT.")

    clearance_misc_journal_id = fields.Many2one(
        'account.journal', string="Clearance Miscellaneous Journal",
        domain="[('type', '=', 'general')]",
        help="Journal used for advance-justification entries.",
    )
    clearance_sale_journal_id = fields.Many2one(
        'account.journal', string="Clearance Sales Journal",
        domain="[('type', '=', 'sale')]",
        help="Journal the client clearance invoice is raised in. "
             "Empty = the company's first sales journal.",
    )
    clearance_waiver_approver_ids = fields.Many2many(
        'res.users', 'clearance_waiver_approver_rel', string="Waiver Approvers",
        help="Who may approve starting work with incomplete documentation. "
             "Empty = any Clearance Manager.")
    clearance_expense_approver_ids = fields.Many2many(
        'res.users', 'clearance_expense_approver_rel', string="Expense Approvers",
        help="Who may approve expenses before disbursement. "
             "Empty = any Clearance Manager.")
    clearance_finance_approver_ids = fields.Many2many(
        'res.users', 'clearance_finance_approver_rel', string="Disbursement (Finance) Approvers",
        help="Who may settle disbursements and justify advances. "
             "Empty = any Clearance Finance user.")
    clearance_billing_service_approver_ids = fields.Many2many(
        'res.users', 'res_company_clearance_billing_service_approver_rel',
        'company_id', 'user_id', string="Billable Service Approvers",
        help="Who may approve a new billable service proposed by Billing. "
             "Empty = any Operations Manager.")

    clearance_billing_approver_ids = fields.Many2many(
        'res.users', 'clearance_billing_approver_rel', string="Billing Approvers",
        help="Who may raise the client invoice and mark files complete. "
             "Empty = any Clearance Finance user.")
    clearance_settlement_approver_ids = fields.Many2many(
        'res.users', 'clearance_settlement_approver_rel',
        string="Settlement Approvers",
        help="Who may approve how an expense is paid once Finance has set "
             "the payment mode, vendor, holder and journal. Empty = any "
             "Clearance Finance Manager.")
    clearance_ops_close_approver_ids = fields.Many2many(
        'res.users', 'clearance_ops_close_approver_rel',
        string="Operations Close Approvers",
        help="Who may close a file for operations. Empty = any Clearance "
             "Operations Manager.")
    clearance_justification_approver_ids = fields.Many2many(
        'res.users', 'clearance_justification_approver_rel',
        string="Justification Approvers",
        help="Who may approve that the documents attached to a staff advance "
             "really justify it. Empty = any Clearance Operations Manager.")
    clearance_recharge_ops_approver_ids = fields.Many2many(
        'res.users', 'clearance_recharge_ops_approver_rel',
        string="Recharge Adjustment Approvers (Operations)",
        help="Who may approve recharging the client at anything other than "
             "cost. Empty = any Clearance Operations Manager.")
    clearance_recharge_gm_approver_ids = fields.Many2many(
        'res.users', 'clearance_recharge_gm_approver_rel',
        string="Below-Cost Recharge Approvers (General Manager)",
        help="Who must also approve when the recharge is BELOW what was "
             "actually disbursed - the company is absorbing the difference. "
             "Empty = any Clearance Manager.")
    clearance_cashier_approver_ids = fields.Many2many(
        'res.users', 'clearance_cashier_approver_rel',
        string="Cashiers",
        help="Who may disburse from a cash till once the Finance Manager "
             "has approved the settlement. Empty = any Clearance Cashier.")
    clearance_treasury_approver_ids = fields.Many2many(
        'res.users', 'clearance_treasury_approver_rel',
        string="Treasury",
        help="Who may pay from a bank or mobile-money journal once the "
             "Finance Manager has approved the settlement. Empty = any "
             "Clearance Treasury user.")
    clearance_reopen_imported_approver_ids = fields.Many2many(
        'res.users', 'clearance_reopen_imported_approver_rel',
        string="Imported-File Reopening Approvers",
        help="Who may approve reopening a file imported from the legacy "
             "system so it can be worked and billed again. Empty = any "
             "Clearance Operations Manager.")
    clearance_advance_waiver_approver_ids = fields.Many2many(
        'res.users', 'clearance_advance_waiver_approver_rel',
        string="Unjustified Advance Waiver Approvers",
        help="Who may allow a file to be billed while a staff advance is "
             "still unjustified. Empty = any Clearance Operations Manager.")

    def _clearance_check_approver(self, kind):
        """Enforce the configured approver list for a checkpoint; fall back
        to the default security group when no list is configured."""
        self.ensure_one()
        field_name, group_xmlids, label = APPROVAL_KINDS[kind]
        approvers = self[field_name]
        user = self.env.user
        if approvers:
            if user not in approvers:
                raise UserError(self.env._(
                    "You are not among the users configured to %(what)s "
                    "(Settings → Clearance).", what=label))
        elif not any(user.has_group(g) for g in group_xmlids):
            raise UserError(self.env._(
                "You do not have the rights to %(what)s.", what=label))
