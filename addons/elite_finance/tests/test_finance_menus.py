"""The Finance app as Elimelec reads it (owner, 11/10/2026).

Reports is a section of Finance holding the OCA reports, the statements
and Odoo's analyses; Customers and Vendors carry their own reports,
opened on their own accounts and previewed on screen; the two SYSCOHADA
statements compute.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.elite_finance.hooks import apply_finance_labels


@tagged('post_install', '-at_install')
class TestFinanceMenus(TransactionCase):

    def test_01_reports_is_a_section_of_finance(self):
        ref = self.env.ref
        reports = ref('account_financial_report.menu_oca_reports')
        self.assertEqual(reports.name, "Reports")
        self.assertEqual(reports.parent_id, ref('account.menu_finance'))
        self.assertEqual(ref('mis_builder.mis_report_finance_menu').parent_id, reports)
        self.assertEqual(ref('mis_builder.mis_report_finance_menu').name, "Financial Statements")
        self.assertEqual(ref('account.account_reports_management_menu').parent_id, reports)
        self.assertFalse(ref('account.menu_finance_reports').active)
        # the six OCA reports still hang under it
        self.assertEqual(
            ref('account_financial_report.menu_trial_balance_wizard').parent_id, reports)

    def test_02_customers_and_vendors_carry_their_reports(self):
        ref = self.env.ref
        customers = ref('account.menu_finance_receivables')
        vendors = ref('account.menu_finance_payables')
        for xmlid, parent in (
                ('elite_finance.menu_customer_ledger', customers),
                ('elite_finance.menu_customer_open_items', customers),
                ('elite_finance.menu_aged_receivables', customers),
                ('elite_finance.menu_vendor_ledger', vendors),
                ('elite_finance.menu_vendor_open_items', vendors),
                ('elite_finance.menu_aged_payables', vendors)):
            self.assertEqual(ref(xmlid).parent_id, parent, xmlid)
            self.assertTrue(ref(xmlid).action, xmlid)

    def test_03_a_customer_report_opens_on_receivable_accounts_and_previews(self):
        Account = self.env['account.account']
        receivable = Account.search([('account_type', '=', 'asset_receivable')])
        payable = Account.search([('account_type', '=', 'liability_payable')])
        self.assertTrue(receivable and payable)
        for model in ('general.ledger.report.wizard', 'open.items.report.wizard',
                      'aged.partner.balance.report.wizard'):
            wizard = self.env[model].with_context(
                elite_finance_partner_type='receivable').create({})
            self.assertTrue(wizard.receivable_accounts_only, model)
            self.assertFalse(wizard.payable_accounts_only, model)
            self.assertTrue(wizard.account_ids, model)
            self.assertFalse(wizard.account_ids - receivable, model)
            # the on-screen preview: the View button's method returns an action
            action = wizard.button_export_html()
            self.assertEqual(action.get('type'), 'ir.actions.report', model)
            self.assertEqual(action.get('report_type'), 'qweb-html', model)
        vendor = self.env['open.items.report.wizard'].with_context(
            elite_finance_partner_type='payable').create({})
        self.assertTrue(vendor.payable_accounts_only)
        self.assertFalse(vendor.account_ids - payable)
        # no context: the wizard is untouched
        plain = self.env['open.items.report.wizard'].create({})
        self.assertFalse(plain.receivable_accounts_only or plain.payable_accounts_only)

    def test_04_labels_in_every_active_language(self):
        self.env['res.lang']._activate_lang('fr_FR')
        reports = self.env.ref('account_financial_report.menu_oca_reports')
        reports.update_field_translations('name', {'fr_FR': "Rapports comptables OCA"})
        apply_finance_labels(self.env)
        self.assertEqual(reports.with_context(lang='fr_FR').name, "Rapports")
        self.assertEqual(reports.with_context(lang='en_US').name, "Reports")
        aged = self.env.ref('elite_finance.menu_aged_receivables')
        self.assertEqual(aged.with_context(lang='fr_FR').name, "Balance âgée clients")

    def test_05_the_syscohada_statements_compute(self):
        ref = self.env.ref
        for xmlid, kpis in (
                ('elite_finance.mis_instance_compte_de_resultat', 23),
                ('elite_finance.mis_instance_bilan', 12)):
            instance = ref(xmlid)
            self.assertEqual(len(instance.report_id.kpi_ids), kpis, xmlid)
            data = instance.compute()
            # auto-expanded lines add one row per account with movements
            self.assertGreaterEqual(len(data['body']), kpis, xmlid)
            errors = [cell for row in data['body'] for cell in row['cells']
                      if cell.get('val') is None and cell.get('val_r')]
            self.assertFalse(errors, xmlid)
