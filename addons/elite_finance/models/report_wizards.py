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

from odoo import api, fields, models

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
        # The viewer creates the wizard with no values at all. Most OCA
        # wizards default their dates to the fiscal year to date; the
        # journal ledger does not, and its dates are required.
        today = fields.Date.context_today(self)
        if 'date_to' in self._fields and not res.get('date_to'):
            res['date_to'] = today
        if 'date_from' in self._fields and self._fields['date_from'].required \
                and not res.get('date_from'):
            company = self.env['res.company'].browse(res.get('company_id')) if res.get('company_id') \
                else self.env.company
            res['date_from'] = company.compute_fiscalyear_dates(today)['date_from']
        if 'date_at' in self._fields and not res.get('date_at'):
            res['date_at'] = today
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

    # Every export of these reports renders bare figures: no currency
    # symbol after each amount, the currency's own decimals (see
    # ir_qweb_fields.py). The flag rides in the action's context, which
    # is what the HTML route and the PDF download render under. The
    # mixin is listed FIRST in each wizard's _inherit so these win over
    # the OCA abstract wizard's own methods.
    def button_export_html(self):
        return super(ReportViewerMixin, self.with_context(
            elite_finance_bare_amounts=True)).button_export_html()

    def button_export_pdf(self):
        return super(ReportViewerMixin, self.with_context(
            elite_finance_bare_amounts=True)).button_export_pdf()

    def button_export_xlsx(self):
        return super(ReportViewerMixin, self.with_context(
            elite_finance_bare_amounts=True)).button_export_xlsx()

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
    _inherit = ['elite_finance.report_viewer_mixin', 'general.ledger.report.wizard']


class JournalLedgerWizard(models.TransientModel):
    _name = 'journal.ledger.report.wizard'
    _inherit = ['elite_finance.report_viewer_mixin', 'journal.ledger.report.wizard']


class TrialBalanceWizard(models.TransientModel):
    _name = 'trial.balance.report.wizard'
    _inherit = ['elite_finance.report_viewer_mixin', 'trial.balance.report.wizard']


class OpenItemsWizard(models.TransientModel):
    _name = 'open.items.report.wizard'
    _inherit = ['elite_finance.report_viewer_mixin', 'open.items.report.wizard']


class AgedPartnerBalanceWizard(models.TransientModel):
    _name = 'aged.partner.balance.report.wizard'
    _inherit = ['elite_finance.report_viewer_mixin', 'aged.partner.balance.report.wizard']


class VatReportWizard(models.TransientModel):
    _name = 'vat.report.wizard'
    _inherit = ['elite_finance.report_viewer_mixin', 'vat.report.wizard']
