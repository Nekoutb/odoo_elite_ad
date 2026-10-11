"""The customer and vendor reports open on their own accounts.

The Customers and Vendors sections of Finance carry the ledger, the open
items and the aged balance (owner, 11/10/2026). Each is the OCA wizard,
opened with context key ``elite_finance_partner_type`` = 'receivable' or
'payable': the matching "accounts only" switch is ticked and the account
list filled the way the wizard's own onchange would fill it, so the
screen opens ready to View, and the user may still widen it.

A context default alone would tick the switch but leave the account
list empty, because defaults do not run the onchange that fills it.
"""

from odoo import api, models


class PartnerTypeDefaults(models.AbstractModel):
    _name = 'elite_finance.partner_type_defaults'
    _description = "Defaults of a report opened for customers or vendors"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        kind = self.env.context.get('elite_finance_partner_type')
        if kind in ('receivable', 'payable'):
            res['receivable_accounts_only'] = kind == 'receivable'
            res['payable_accounts_only'] = kind == 'payable'
            # the same search the wizard's onchange_type_accounts_only
            # runs - done here directly, because a draft record built
            # inside default_get recursed on the way to writing it
            company_id = res.get('company_id') or self.env.company.id
            accounts = self.env['account.account'].search([
                ('company_ids', 'in', [company_id]),
                ('account_type', '=',
                 'asset_receivable' if kind == 'receivable' else 'liability_payable'),
            ])
            res['account_ids'] = [(6, 0, accounts.ids)]
        return res


class GeneralLedgerWizard(models.TransientModel):
    _name = 'general.ledger.report.wizard'
    _inherit = ['general.ledger.report.wizard', 'elite_finance.partner_type_defaults']


class OpenItemsWizard(models.TransientModel):
    _name = 'open.items.report.wizard'
    _inherit = ['open.items.report.wizard', 'elite_finance.partner_type_defaults']


class AgedPartnerBalanceWizard(models.TransientModel):
    _name = 'aged.partner.balance.report.wizard'
    _inherit = ['aged.partner.balance.report.wizard', 'elite_finance.partner_type_defaults']
