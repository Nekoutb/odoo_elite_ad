"""The Clearance Administrator (owner, 07/10/2026): one role that may
do everything the application does, without being an Odoo administrator.
The proof is a file walked from opening to closing by that one user."""

import base64

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestClearanceAdmin(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'A4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'A70621', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'A65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'A75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales admin", 'type': 'sale', 'code': 'ASALS'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_commission_account_id': cls.fee.id,
            'clearance_service_fee_account_id': cls.fee.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash admin", 'type': 'cash', 'code': 'ACSHS'})
        cls.client = env['res.partner'].create({
            'name': "Admin Client", 'is_company': True,
            'street': "BP 11 Douala", 'email': "admin-client@test.cm",
            'vat': "M000000000051A",
            'company_registry': "RC/DLA/2026/B/0051",
            'clearance_invoice_name': "ADMIN CLIENT SARL"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal Admin", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port admin", 'code': "A-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Admin test", 'code': "A-ADM", 'commission_rate': 2.0})
        cls.boss = env['res.users'].create({
            'name': "Clearance Boss", 'login': "boss@adm.test",
            'group_ids': [(6, 0, [env.ref(
                'elite_clearance.group_clearance_admin').id])]})

    def test_01_the_role_is_every_role_and_not_an_odoo_administrator(self):
        boss = self.boss
        for group in ('customer_service', 'customer_service_manager',
                      'operations', 'ops_manager', 'transit', 'transit_manager',
                      'finance', 'finance_manager', 'cashier', 'treasury',
                      'billing', 'billing_manager', 'manager'):
            self.assertTrue(
                boss.has_group('elite_clearance.group_clearance_' + group), group)
        self.assertTrue(boss.has_group('account.group_account_manager'))
        self.assertFalse(boss.has_group('base.group_system'),
                         "everything in Clearance, not everything in Odoo")

    def test_02_one_person_walks_a_file_from_opening_to_closing(self):
        boss = self.boss
        File = self.env['logistics.file'].with_user(boss)
        file = File.create({
            'customs_regime': 'im4', 'partner_id': self.client.id,
            'service_type_id': self.service.id,
            'bl_awb_ref': "MEDUA000077",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0, 'package_count': 12,
            'weight_kg': 800.0, 'not_containerised': True})
        file.action_request_opening()
        file.action_approve_opening()
        self.assertEqual(file.state, 'in_progress')

        # keys a cost (the "Finance never keys" rule steps aside), and it
        # belongs to no team, so they approve it themselves as any head
        Expense = self.env['logistics.expense'].with_user(boss)
        exp = Expense.create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Handling", 'amount': 50000,
            'journal_id': self.cash.id, 'vendor_id': self.vendor.id})
        self.assertFalse(exp.originating_team)
        self.assertEqual(exp.payment_mode, 'cash')
        exp.action_submit()
        exp.action_approve()
        exp.action_submit_settlement()
        exp.action_approve_settlement()
        wizard = self.env['logistics.expense.settle.wizard'].with_user(
            boss).with_context(active_id=exp.id).create({})
        receipt = self.env['ir.attachment'].with_user(boss).create({
            'name': "recu.pdf", 'res_model': wizard._name, 'res_id': wizard.id,
            'datas': base64.b64encode(b"%PDF-1.4 admin")})
        wizard.write({'attachment_ids': [(4, receipt.id)]})
        wizard.action_pay()
        self.assertEqual(exp.state, 'settled')

        file.customs_fee_amount = 30000
        file.action_close_operations()
        self.assertEqual(file.state, 'ops_closed')
        self.env['logistics.billing.wizard'].with_user(boss).with_context(
            active_id=file.id).create({}).action_create_invoice()
        self.assertTrue(file.invoice_id)
        file.invoice_id.with_user(boss).action_post()
        file.action_mark_complete()
        self.assertEqual(file.state, 'done')
        self.assertEqual(file.create_uid, boss)

    def test_03_the_settings_page_is_theirs_too(self):
        wizard = self.env['clearance.settings.wizard'].with_user(self.boss).create(
            {'clearance_invoice_complaint_days': 21})
        self.assertEqual(self.env.company.clearance_invoice_complaint_days, 21)
        self.assertEqual(wizard.company_id, self.env.company)
