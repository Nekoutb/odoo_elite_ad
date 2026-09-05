from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

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
        related='company_id.clearance_billing_service_approver_ids',
        readonly=False)
    clearance_settlement_approver_ids = fields.Many2many(
        related='company_id.clearance_settlement_approver_ids', readonly=False)
    clearance_ops_close_approver_ids = fields.Many2many(
        related='company_id.clearance_ops_close_approver_ids', readonly=False)
    clearance_oop_undercharge_account_id = fields.Many2one(
        related='company_id.clearance_oop_undercharge_account_id', readonly=False)
    clearance_oop_overcharge_account_id = fields.Many2one(
        related='company_id.clearance_oop_overcharge_account_id', readonly=False)
    clearance_commission_account_id = fields.Many2one(
        related='company_id.clearance_commission_account_id', readonly=False)
    clearance_service_fee_account_id = fields.Many2one(
        related='company_id.clearance_service_fee_account_id', readonly=False)
    clearance_justification_approver_ids = fields.Many2many(
        related='company_id.clearance_justification_approver_ids', readonly=False)
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
