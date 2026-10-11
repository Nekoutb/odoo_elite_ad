"""The accounting app is called Finance (owner, 11/10/2026).

Community labels account's root menu "Invoicing" and Enterprise relabels
it "Accounting"; Elimelec's teams call the department Finance, in both
languages. The data record sets the English label; the hook writes the
same word into every active language, so a French user does not keep
reading "Facturation".
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.elite_clearance.hooks import rename_finance_menu


@tagged('post_install', '-at_install')
class TestFinanceMenu(TransactionCase):

    def test_01_the_root_menu_reads_finance_in_english(self):
        self.assertEqual(self.env.ref('account.menu_finance').name, "Finance")

    def test_02_the_hook_writes_every_active_language(self):
        lang = self.env['res.lang']._activate_lang('fr_FR')
        self.assertTrue(lang.active)
        menu = self.env.ref('account.menu_finance')
        # what an upgraded database carries: the French label of before
        menu.update_field_translations('name', {'fr_FR': "Facturation"})
        self.assertEqual(menu.with_context(lang='fr_FR').name, "Facturation")
        rename_finance_menu(self.env)
        self.assertEqual(menu.with_context(lang='fr_FR').name, "Finance")
        self.assertEqual(menu.with_context(lang='en_US').name, "Finance")
