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
    clearance_waiver_approver_ids = fields.Many2many(
        related='company_id.clearance_waiver_approver_ids', readonly=False)
    clearance_expense_approver_ids = fields.Many2many(
        related='company_id.clearance_expense_approver_ids', readonly=False)
    clearance_finance_approver_ids = fields.Many2many(
        related='company_id.clearance_finance_approver_ids', readonly=False)
    clearance_billing_approver_ids = fields.Many2many(
        related='company_id.clearance_billing_approver_ids', readonly=False)
