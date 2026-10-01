"""The General Manager's settings page (owner, 01/10/2026).

Odoo's own settings page is for administrators only - core's
`res.config.settings.execute()` refuses everybody else - so the General
Manager maintains the Clearance settings on a page of ours that writes
the company under sudo once the group is checked.
"""

from odoo.exceptions import AccessError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestClearanceSettings(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env

        def user(name, group):
            return env['res.users'].create({
                'name': name, 'login': name.lower().replace(' ', '.') + "@set.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.gm = user("Settings GM", 'manager')
        cls.plain = user("Settings Plain", 'user')
        cls.ops_head = user("Settings Ops Head", 'ops_manager')
        cls.journal = env['account.journal'].create({
            'name': "Misc settings", 'type': 'general', 'code': 'SMISC'})

    def test_01_the_general_manager_writes_the_company_without_being_admin(self):
        self.assertFalse(self.gm.has_group('base.group_system'))
        company = self.env.company
        with Form(self.env['clearance.settings.wizard'].with_user(self.gm)) as form:
            self.assertEqual(form.company_id, company)
            form.clearance_invoice_complaint_days = 15
            form.clearance_misc_journal_id = self.journal
            form.clearance_file_close_approver_ids.add(self.gm)
        self.assertEqual(company.clearance_invoice_complaint_days, 15)
        self.assertEqual(company.clearance_misc_journal_id, self.journal)
        self.assertIn(self.gm, company.clearance_file_close_approver_ids)
        # and the page reads back what stands
        again = self.env['clearance.settings.wizard'].with_user(self.gm).create({})
        self.assertEqual(again.clearance_invoice_complaint_days, 15)
        self.assertEqual(again.clearance_misc_journal_id, self.journal)

    def test_02_the_dropdowns_can_be_filled_by_that_user(self):
        """A Many2one the user cannot search is a field they cannot set:
        the journal and numbering fields read models Odoo opens to
        accounting users only, so the General Manager carries read-only
        accounting."""
        for model in ('account.account', 'account.journal', 'account.tax',
                      'ir.sequence', 'res.users', 'res.partner.bank'):
            self.env[model].with_user(self.gm).search([], limit=1)

    def test_03_nobody_else_and_not_through_sudo(self):
        Wizard = self.env['clearance.settings.wizard']
        with self.assertRaises(AccessError):
            Wizard.with_user(self.plain).create(
                {'clearance_invoice_complaint_days': 9})
        with self.assertRaises(AccessError):
            Wizard.with_user(self.ops_head).create(
                {'clearance_invoice_complaint_days': 9})
        with self.assertRaises(AccessError,
                               msg="sudo() keeps the user; the group is "
                                   "checked on the user"):
            Wizard.with_user(self.plain).sudo().create(
                {'clearance_invoice_complaint_days': 9})
        self.assertNotEqual(self.env.company.clearance_invoice_complaint_days, 9)

    def test_04_the_menu_is_the_general_managers(self):
        menu = self.env.ref('elite_clearance.menu_clearance_settings')
        self.assertEqual(menu.action.res_model, 'clearance.settings.wizard')
        # `in`, not equal: a database upgraded from the administrator-only
        # build keeps base.group_system on the menu beside the manager
        # group - a menuitem's groups are added on upgrade, never
        # replaced - and menu groups are OR-ed, so that changes nothing.
        self.assertIn(self.env.ref('elite_clearance.group_clearance_manager'),
                      menu.group_ids)
