"""The General Manager's Clearance settings page.

Odoo's own settings page (res.config.settings) refuses everybody who is
not an administrator - `execute()` raises for a non-admin, and that is
core, which we never edit. The owner (01/10/2026) wants the General
Manager to maintain the Clearance settings without being made an
administrator of the whole database. So the same fields are offered
here, on a page of our own: they are related to the company so the
form reads what stands, and `create()` / `write()` apply the values to
the company under sudo - after checking the caller IS a General
Manager, because the ACL alone would let a sudo() slip past the group.
The administrator's page stays where it was (Settings -> Clearance)
and both write the same company fields.
"""

from odoo import api, fields, models
from odoo.exceptions import AccessError

MANAGER_GROUP = 'elite_clearance.group_clearance_manager'


class ClearanceSettingsWizard(models.TransientModel):
    _name = 'clearance.settings.wizard'
    _description = "Clearance Settings"

    company_id = fields.Many2one(
        'res.company', required=True, readonly=True,
        default=lambda self: self.env.company)

    clearance_oop_account_id = fields.Many2one(
        related='company_id.clearance_oop_account_id', readonly=False)
    clearance_advance_account_id = fields.Many2one(
        related='company_id.clearance_advance_account_id', readonly=False)
    clearance_fee_account_id = fields.Many2one(
        related='company_id.clearance_fee_account_id', readonly=False)
    clearance_misc_journal_id = fields.Many2one(
        related='company_id.clearance_misc_journal_id', readonly=False)
    clearance_sale_journal_id = fields.Many2one(
        related='company_id.clearance_sale_journal_id', readonly=False)
    clearance_service_tax_ids = fields.Many2many(
        related='company_id.clearance_service_tax_ids', readonly=False)
    clearance_invoice_title = fields.Char(
        related='company_id.clearance_invoice_title', readonly=False)
    clearance_letterhead_tagline = fields.Char(
        related='company_id.clearance_letterhead_tagline', readonly=False)
    clearance_cash_voucher_title = fields.Char(
        related='company_id.clearance_cash_voucher_title', readonly=False)
    clearance_invoice_vat_label = fields.Char(
        related='company_id.clearance_invoice_vat_label', readonly=False)
    clearance_invoice_payment_terms = fields.Char(
        related='company_id.clearance_invoice_payment_terms', readonly=False)
    clearance_invoice_complaint_days = fields.Integer(
        related='company_id.clearance_invoice_complaint_days', readonly=False)
    clearance_invoice_bank_ids = fields.Many2many(
        related='company_id.clearance_invoice_bank_ids', readonly=False)
    clearance_waiver_approver_ids = fields.Many2many(
        related='company_id.clearance_waiver_approver_ids', readonly=False)
    clearance_expense_approver_ids = fields.Many2many(
        related='company_id.clearance_expense_approver_ids', readonly=False)
    clearance_finance_approver_ids = fields.Many2many(
        related='company_id.clearance_finance_approver_ids', readonly=False)
    clearance_billing_approver_ids = fields.Many2many(
        related='company_id.clearance_billing_approver_ids', readonly=False)
    clearance_billing_service_approver_ids = fields.Many2many(
        related='company_id.clearance_billing_service_approver_ids', readonly=False)
    clearance_settlement_approver_ids = fields.Many2many(
        related='company_id.clearance_settlement_approver_ids', readonly=False)
    clearance_ops_close_approver_ids = fields.Many2many(
        related='company_id.clearance_ops_close_approver_ids', readonly=False)
    clearance_reopen_approver_ids = fields.Many2many(
        related='company_id.clearance_reopen_approver_ids', readonly=False)
    clearance_file_open_approver_ids = fields.Many2many(
        related='company_id.clearance_file_open_approver_ids', readonly=False)
    clearance_file_close_approver_ids = fields.Many2many(
        related='company_id.clearance_file_close_approver_ids', readonly=False)
    clearance_oop_undercharge_account_id = fields.Many2one(
        related='company_id.clearance_oop_undercharge_account_id', readonly=False)
    clearance_oop_overcharge_account_id = fields.Many2one(
        related='company_id.clearance_oop_overcharge_account_id', readonly=False)
    clearance_commission_account_id = fields.Many2one(
        related='company_id.clearance_commission_account_id', readonly=False)
    clearance_service_fee_account_id = fields.Many2one(
        related='company_id.clearance_service_fee_account_id', readonly=False)
    clearance_file_fee_account_id = fields.Many2one(
        related='company_id.clearance_file_fee_account_id', readonly=False)
    clearance_credit_note_title = fields.Char(
        related='company_id.clearance_credit_note_title', readonly=False)
    clearance_oop_payable_account_id = fields.Many2one(
        related='company_id.clearance_oop_payable_account_id', readonly=False)
    clearance_undisclosed_file_sequence_id = fields.Many2one(
        related='company_id.clearance_undisclosed_file_sequence_id', readonly=False)
    clearance_undisclosed_invoice_sequence_id = fields.Many2one(
        related='company_id.clearance_undisclosed_invoice_sequence_id', readonly=False)
    clearance_justification_approver_ids = fields.Many2many(
        related='company_id.clearance_justification_approver_ids', readonly=False)
    clearance_justification_finance_approver_ids = fields.Many2many(
        related='company_id.clearance_justification_finance_approver_ids', readonly=False)
    clearance_recharge_ops_approver_ids = fields.Many2many(
        related='company_id.clearance_recharge_ops_approver_ids', readonly=False)
    clearance_recharge_gm_approver_ids = fields.Many2many(
        related='company_id.clearance_recharge_gm_approver_ids', readonly=False)
    clearance_cashier_approver_ids = fields.Many2many(
        related='company_id.clearance_cashier_approver_ids', readonly=False)
    clearance_treasury_approver_ids = fields.Many2many(
        related='company_id.clearance_treasury_approver_ids', readonly=False)
    clearance_reopen_imported_approver_ids = fields.Many2many(
        related='company_id.clearance_reopen_imported_approver_ids', readonly=False)
    clearance_advance_waiver_approver_ids = fields.Many2many(
        related='company_id.clearance_advance_waiver_approver_ids', readonly=False)
    account_storno = fields.Boolean(
        related='company_id.account_storno', readonly=False)

    # the fields the page writes to the company; everything above
    SETTINGS = (
        'clearance_oop_account_id',
        'clearance_advance_account_id',
        'clearance_fee_account_id',
        'clearance_misc_journal_id',
        'clearance_sale_journal_id',
        'clearance_service_tax_ids',
        'clearance_invoice_title',
        'clearance_letterhead_tagline',
        'clearance_cash_voucher_title',
        'clearance_invoice_vat_label',
        'clearance_invoice_payment_terms',
        'clearance_invoice_complaint_days',
        'clearance_invoice_bank_ids',
        'clearance_waiver_approver_ids',
        'clearance_expense_approver_ids',
        'clearance_finance_approver_ids',
        'clearance_billing_approver_ids',
        'clearance_billing_service_approver_ids',
        'clearance_settlement_approver_ids',
        'clearance_ops_close_approver_ids',
        'clearance_reopen_approver_ids',
        'clearance_file_open_approver_ids',
        'clearance_file_close_approver_ids',
        'clearance_oop_undercharge_account_id',
        'clearance_oop_overcharge_account_id',
        'clearance_commission_account_id',
        'clearance_service_fee_account_id',
        'clearance_file_fee_account_id',
        'clearance_credit_note_title',
        'clearance_oop_payable_account_id',
        'clearance_undisclosed_file_sequence_id',
        'clearance_undisclosed_invoice_sequence_id',
        'clearance_justification_approver_ids',
        'clearance_justification_finance_approver_ids',
        'clearance_recharge_ops_approver_ids',
        'clearance_recharge_gm_approver_ids',
        'clearance_cashier_approver_ids',
        'clearance_treasury_approver_ids',
        'clearance_reopen_imported_approver_ids',
        'clearance_advance_waiver_approver_ids',
        'account_storno',
    )

    def _check_manager(self):
        # env.user, not env.su: sudo() keeps the user, and a plain user's
        # sudo() must not be a way in
        if not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(self.env._(
                "Only a General Manager may change the Clearance settings."))

    @api.model
    def _apply(self, company, vals):
        """Write the settings to the company, as the company's keeper.

        The related fields would do this by themselves, as the current
        user - who has no write right on res.company and is not meant
        to get one. Taking the values out of `vals` leaves the related
        fields to be recomputed from the company just written.
        """
        settings = {k: vals.pop(k) for k in list(vals) if k in self.SETTINGS}
        if settings:
            self._check_manager()
            company.sudo().write(settings)
        return settings

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id)
            self._apply(company, vals)
        return super().create(vals_list)

    def write(self, vals):
        for wizard in self:
            self._apply(wizard.company_id, dict(vals))
        vals = {k: v for k, v in vals.items() if k not in self.SETTINGS}
        return super().write(vals) if vals else True

    def action_save(self):
        """The form's own Save has already written the company; this
        button only exists so the page has an obvious way out."""
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_open_file_numbering(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'elite_clearance.action_logistics_service_type_numbering')

    def action_open_turnaround_targets(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'elite_clearance.action_clearance_turnaround_target')
