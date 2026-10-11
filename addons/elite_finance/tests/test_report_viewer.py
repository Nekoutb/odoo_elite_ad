"""Every report opens at once (owner, 11/10/2026).

The six OCA menu entries run the viewer; the viewer's state method
returns the HTML report for the wizard's defaults and the quick filters
to show; the two statements open directly on their result page.
"""

from odoo.tests import TransactionCase, tagged

WIZARDS = (
    'general.ledger.report.wizard', 'journal.ledger.report.wizard',
    'trial.balance.report.wizard', 'open.items.report.wizard',
    'aged.partner.balance.report.wizard', 'vat.report.wizard',
)


@tagged('post_install', '-at_install')
class TestReportViewer(TransactionCase):

    def test_01_the_six_report_menus_run_the_viewer(self):
        ref = self.env.ref
        for menu, action in (
                ('account_financial_report.menu_general_ledger_wizard', 'elite_finance.action_view_general_ledger'),
                ('account_financial_report.menu_journal_ledger_wizard', 'elite_finance.action_view_journal_ledger'),
                ('account_financial_report.menu_trial_balance_wizard', 'elite_finance.action_view_trial_balance'),
                ('account_financial_report.menu_open_items_wizard', 'elite_finance.action_view_open_items'),
                ('account_financial_report.menu_aged_partner_balance_wizard', 'elite_finance.action_view_aged_partner_balance'),
                ('account_financial_report.menu_vat_report_wizard', 'elite_finance.action_view_vat_report'),
                ('elite_finance.menu_customer_ledger', 'elite_finance.client_customer_ledger'),
                ('elite_finance.menu_aged_payables', 'elite_finance.client_aged_payables')):
            self.assertEqual(ref(menu).action, ref(action), menu)
            self.assertEqual(ref(action).tag, 'elite_finance_report_viewer')

    def test_02_the_state_is_the_html_report_and_the_quick_filters(self):
        for model in WIZARDS:
            wizard = self.env[model].create({})
            state = wizard.elite_finance_viewer_state()
            self.assertTrue(state['report_name'], model)
            self.assertTrue(state['data'], model)
            names = [f['name'] for f in state['fields']]
            self.assertTrue(names, model)
            if 'date_at' in wizard._fields:
                self.assertIn('date_at', names, model)
                self.assertTrue(state['filters']['date_at'], model)
            else:
                self.assertEqual(names[:2], ['date_from', 'date_to'], model)
                self.assertTrue(state['filters']['date_from'] < state['filters']['date_to'], model)
            if 'target_move' in wizard._fields:
                entries = next(f for f in state['fields'] if f['name'] == 'target_move')
                self.assertEqual(entries['type'], 'selection')
                self.assertEqual([o['value'] for o in entries['options']], ['posted', 'all'])
                self.assertEqual(state['filters']['target_move'], 'posted', model)

    def test_03_a_changed_filter_changes_the_report_data(self):
        wizard = self.env['general.ledger.report.wizard'].create({})
        before = wizard.elite_finance_viewer_state()['data']
        wizard.write({'target_move': 'all', 'date_from': '2026-01-01'})
        after = wizard.elite_finance_viewer_state()['data']
        self.assertNotEqual(before, after)

    def test_04_the_figures_carry_no_currency_symbol_and_no_stray_decimals(self):
        self.env.company.external_report_layout_id = self.env.ref('web.external_layout_standard')
        currency = self.env.company.currency_id
        wizard = self.env['trial.balance.report.wizard'].create({})
        state = wizard.elite_finance_viewer_state()
        self.assertTrue(state['context'].get('elite_finance_bare_amounts'),
                        "the flag rides in the action context the viewer renders under")
        html = self.env['ir.actions.report'].with_context(
            **state['context'])._render_qweb_html(
                state['report_name'], wizard.ids, data=state['data'])[0].decode()
        self.assertIn('oe_currency_value', html)
        self.assertNotIn(currency.symbol, html.split('<div class="article', 1)[1],
                         "no symbol after the figures (the title may name the currency)")
        if currency.decimal_places == 0:
            self.assertNotRegex(html, r'oe_currency_value">[\d,. ]*[.,]\d\d<')
        # the exports carry the flag too
        for method in ('button_export_pdf', 'button_export_xlsx'):
            action = getattr(wizard.with_context(discard_logo_check=True), method)()
            self.assertTrue(action['context'].get('elite_finance_bare_amounts'), method)
        # and nothing outside these reports is touched
        plain = self.env['ir.qweb.field.monetary'].value_to_html(
            1234.0, {'display_currency': currency})
        self.assertIn(currency.symbol, plain)

    def test_05_the_trial_balance_is_laid_out_as_enterprise_lays_it_out(self):
        self.env.company.external_report_layout_id = self.env.ref('web.external_layout_standard')
        wizard = self.env['trial.balance.report.wizard'].create({'hide_account_at_0': False})
        state = wizard.elite_finance_viewer_state()
        html = self.env['ir.actions.report'].with_context(
            **state['context'])._render_qweb_html(
                state['report_name'], wizard.ids, data=state['data'])[0].decode()
        # the two-level header: Initial Balance, the period, End Balance
        self.assertIn('tb-group-row', html)
        self.assertIn('Initial Balance', html)
        self.assertIn('End Balance', html)
        self.assertNotIn('Period balance', html, "the period-balance column is gone")
        # code and name in one cell, figures with their sign class
        self.assertRegex(html, r'tb-c1">\s*<span[^>]*res-model="account.account"[^>]*>\s*<b>\d')
        self.assertIn('tb-num tb-c5', html)
        self.assertIn('tb-totals', html)
        # the OCA rows stay for the partner-details layout
        detailed = self.env['trial.balance.report.wizard'].create({'show_partner_details': True})
        dstate = detailed.elite_finance_viewer_state()
        dhtml = self.env['ir.actions.report'].with_context(
            **dstate['context'])._render_qweb_html(
                dstate['report_name'], detailed.ids, data=dstate['data'])[0].decode()
        self.assertNotIn('tb-group-row', dhtml)

    def test_06_the_statements_open_on_their_result_page(self):
        ref = self.env.ref
        for server, instance in (
                ('elite_finance.server_open_bilan', 'elite_finance.mis_instance_bilan'),
                ('elite_finance.server_open_compte_de_resultat', 'elite_finance.mis_instance_compte_de_resultat')):
            action = ref(server).run()
            self.assertEqual(action['res_model'], 'mis.report.instance')
            self.assertEqual(action['res_id'], ref(instance).id)
            self.assertEqual(ref('elite_finance.menu_bilan').action._name, 'ir.actions.server')
