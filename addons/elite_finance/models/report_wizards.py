"""The OCA report wizards, read by the report viewer.

Every report opens AT ONCE, Enterprise-style (owner, 11/10/2026): the
menu runs the client action ``elite_finance_report_viewer``, which
creates the wizard with its defaults (fiscal year to date, posted
entries - the wizard's own), asks ``elite_finance_viewer_state()`` for
the HTML report to show and the filters to offer, and puts the report in
the page under a filter bar. Changing a filter writes the wizard and
asks again. "More filters" opens the wizard's own form in a dialog, with
an Apply button instead of its View/Export buttons.

The Customers and Vendors entries open the same wizards on receivable or
payable accounts only: context key ``elite_finance_partner_type`` ticks
the switch and fills the account list the way the wizard's onchange
would, in ``default_get`` - a context default alone would leave the list
empty, because defaults do not run onchanges.
"""

from odoo import api, models

# the quick filters the bar offers, when the wizard has them
QUICK_FILTERS = (
    ('date_from', "From", 'date'),
    ('date_to', "To", 'date'),
    ('date_at', "As at", 'date'),
    ('target_move', "Entries", 'selection'),
)


class ReportViewerMixin(models.AbstractModel):
    _name = 'elite_finance.report_viewer_mixin'
    _description = "What the report viewer needs from an OCA report wizard"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        kind = self.env.context.get('elite_finance_partner_type')
        if kind in ('receivable', 'payable') and 'receivable_accounts_only' in self._fields:
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

    def elite_finance_viewer_state(self):
        """The HTML report for this wizard's current values, and the quick
        filters to show above it."""
        self.ensure_one()
        # discard_logo_check: an administrator would otherwise be sent to
        # the document-layout dialog instead of the report, the first time
        action = self.with_context(discard_logo_check=True).button_export_html()
        filters, fields = {}, []
        for name, label, kind in QUICK_FILTERS:
            field = self._fields.get(name)
            if not field:
                continue
            value = self[name]
            entry = {'name': name, 'label': self.env._(label), 'type': kind,
                     'required': bool(field.required)}
            if kind == 'selection':
                entry['options'] = [
                    {'value': key, 'label': text}
                    for key, text in field._description_selection(self.env)]
            fields.append(entry)
            filters[name] = value.isoformat() if kind == 'date' and value else (value or False)
        return {
            'report_name': action.get('report_name'),
            'data': action.get('data') or {},
            'context': action.get('context') or {},
            'fields': fields,
            'filters': filters,
        }


class GeneralLedgerWizard(models.TransientModel):
    _name = 'general.ledger.report.wizard'
    _inherit = ['general.ledger.report.wizard', 'elite_finance.report_viewer_mixin']


class JournalLedgerWizard(models.TransientModel):
    _name = 'journal.ledger.report.wizard'
    _inherit = ['journal.ledger.report.wizard', 'elite_finance.report_viewer_mixin']


class TrialBalanceWizard(models.TransientModel):
    _name = 'trial.balance.report.wizard'
    _inherit = ['trial.balance.report.wizard', 'elite_finance.report_viewer_mixin']


class OpenItemsWizard(models.TransientModel):
    _name = 'open.items.report.wizard'
    _inherit = ['open.items.report.wizard', 'elite_finance.report_viewer_mixin']


class AgedPartnerBalanceWizard(models.TransientModel):
    _name = 'aged.partner.balance.report.wizard'
    _inherit = ['aged.partner.balance.report.wizard', 'elite_finance.report_viewer_mixin']


class VatReportWizard(models.TransientModel):
    _name = 'vat.report.wizard'
    _inherit = ['vat.report.wizard', 'elite_finance.report_viewer_mixin']
