"""Owner spec 14/10/2026, three instructions: the application is
bilingual and the Clearance Administrator sets each user's language;
the customer record is Customer Service's and a file is not opened
until it is complete; each expense category carries the wording the
client's invoice prints."""

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec1410(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'D4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'D70621', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'D65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'D75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales 1410", 'type': 'sale', 'code': 'DSALS'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_commission_account_id': cls.fee.id,
            'clearance_service_fee_account_id': cls.fee.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'street': "BP 5077 DLA BONAPRISO",
            'company_registry': "RC/DLA/2018/B/2056",
        })
        cls.till = env['account.journal'].create({
            'name': "Caisse 1410", 'type': 'cash', 'code': 'DCSH'})
        cls.client = env['res.partner'].create({
            'name': "Mbalmayo Bois", 'is_company': True,
            'street': "BP 77 Douala", 'email': "bois@test.cm",
            'vat': "M000000000071C",
            'company_registry': "RC/DLA/2026/B/0071",
            'clearance_invoice_name': "MBALMAYO BOIS ET DERIVES SA",
            'clearance_vat_exempt': True})
        # a client Customer Service has only named, as Teese left them
        cls.bare_client = env['res.partner'].create({
            'name': "Nkongsamba Négoce", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Port Autonome Test", 'is_company': True,
            'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Frais de passage", 'code': "D-PAS",
            'alternative_name_ids': [
                (0, 0, {'name': "Redevance portuaire"}),
                (0, 0, {'name': "Frais de manutention portuaire"})]})
        cls.alt_port = cls.category.alternative_name_ids[0]
        cls.alt_handling = cls.category.alternative_name_ids[1]
        cls.plain_category = env['logistics.expense.category'].create({
            'name': "Magasinage", 'code': "D-MAG"})
        cls.service = env['logistics.service.type'].create({
            'name': "Spec 1410", 'code': "D-SPC", 'commission_rate': 2.0})

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@1410.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.cs_agent = user("Solange Mbarga", 'customer_service')
        cls.cs_head = user("CS Head D", 'customer_service_manager')
        cls.ops_agent = user("Ops Agent D", 'operations')
        cls.ops_head = user("Ops Head D", 'ops_manager')
        cls.finance = user("Finance D", 'finance')
        cls.finance_head = user("Finance Head D", 'finance_manager')
        cls.biller = user("Biller D", 'billing')
        cls.admin = user("Clearance Admin D", 'admin')

    # -----------------------------------------------------------------
    def _file(self, user=None, **extra):
        File = self.env['logistics.file']
        if user:
            File = File.with_user(user)
        vals = {
            'customs_regime': 'im4', 'bl_awb_ref': "MEDUD000577",
            'goods_description': "Grumes", 'cargo_value': 1000000.0,
            'package_count': 12, 'weight_kg': 800.0,
            'not_containerised': True,
            'partner_id': self.client.id, 'service_type_id': self.service.id}
        vals.update(extra)
        return File.create(vals)

    def _working_file(self, **extra):
        file = self._file(**extra)
        file.state = 'in_progress'
        return file

    def _settled(self, file, amount=50000, category=None,
                 description="Passage portuaire TC 40'"):
        exp = self.env['logistics.expense'].with_user(self.ops_agent).create({
            'file_id': file.id,
            'category_id': (category or self.category).id,
            'description': description, 'amount': amount,
            'vendor_id': self.vendor.id, 'journal_id': self.till.id})
        exp.action_submit()
        exp.with_user(self.ops_head).action_approve()
        exp.with_user(self.finance).action_submit_settlement()
        exp.with_user(self.finance_head).action_approve_settlement()
        exp = exp.with_env(self.env)        # the suite's root pays it out
        exp.action_settle()
        return exp

    def _wizard(self, file, user=None):
        Wizard = self.env['logistics.billing.wizard']
        if user:
            Wizard = Wizard.with_user(user)
        return Wizard.with_context(active_id=file.id).create({})

    # =================================================================
    # 3. the category's billing name is what the client's invoice prints
    def test_01_the_alternative_name_prints_and_the_ledger_keeps_the_category(self):
        file = self._working_file()
        exp = self._settled(file)
        file.action_close_operations()

        wizard = self._wizard(file, user=self.biller)
        line = wizard.debours_line_ids
        self.assertEqual(line.name, "Frais de passage — Passage portuaire TC 40'",
                         "the description the ledger keeps")
        self.assertFalse(line.alternative_name_id, "nothing chosen yet")
        self.assertEqual(line.print_name,
                         "Frais de passage — Passage portuaire TC 40'",
                         "nothing chosen: the category name prints")
        # the list offers this category's names and no other's
        other = self.env['logistics.expense.category.name'].create({
            'category_id': self.plain_category.id, 'name': "Stockage"})
        offered = self.env['logistics.expense.category.name'].search(
            [('category_id', '=', line.category_id.id)])
        self.assertEqual(offered, self.alt_port + self.alt_handling)
        self.assertNotIn(other, offered)
        line.alternative_name_id = self.alt_port
        self.assertEqual(line.print_name,
                         "Redevance portuaire — Passage portuaire TC 40'")
        wizard.action_create_invoice()
        invoice = file.invoice_id.sudo()
        billed = invoice.invoice_line_ids.filtered(
            lambda l: l.clearance_category == 'debours')
        self.assertEqual(billed.name,
                         "Frais de passage — Passage portuaire TC 40'",
                         "the journal item label is the category")
        self.assertEqual(billed.clearance_print_name,
                         "Redevance portuaire — Passage portuaire TC 40'")
        self.assertEqual(invoice._clearance_designation(billed),
                         "Redevance portuaire — Passage portuaire TC 40'",
                         "and the document prints the billing name")
        self.assertEqual(exp.billing_name_id, self.alt_port,
                         "kept on the expense for the review")
        # the analytic line Odoo writes at posting carries the ledger
        # label, never the client's wording
        invoice.action_post()
        analytic = billed.analytic_line_ids
        self.assertTrue(analytic)
        self.assertNotIn("Redevance", "".join(analytic.mapped('name')))

    def test_02_the_choice_survives_a_review_and_a_credit_note_copies_it(self):
        file = self._working_file()
        exp = self._settled(file)
        file.action_close_operations()

        wizard = self._wizard(file, user=self.biller)
        line = wizard.debours_line_ids
        line.alternative_name_id = self.alt_handling
        # a recharge above cost, so the screen goes through a review and
        # comes back: the choice must survive the round trip
        line.amount_recharged = 55000
        line.comment = "Agreed uplift"
        wizard.action_submit_for_review()
        self.assertEqual(exp.billing_name_id, self.alt_handling,
                         "the biller's choice is kept")
        file.with_user(self.ops_head).action_approve_recharge_ops()
        wizard = self._wizard(file, user=self.biller)
        self.assertEqual(wizard.debours_line_ids.alternative_name_id,
                         self.alt_handling,
                         "and proposed again when the screen is reopened")
        wizard.action_create_invoice()
        invoice = file.invoice_id.sudo()
        billed = invoice.invoice_line_ids.filtered(
            lambda l: l.clearance_category == 'debours')
        self.assertEqual(
            invoice._clearance_designation(billed),
            "Frais de manutention portuaire — Passage portuaire TC 40'")
        self.assertEqual(billed.name,
                         "Frais de passage — Passage portuaire TC 40'")
        # a credit note reverses the same wording
        invoice.action_post()
        credit = invoice._clearance_raise_credit_note(
            billed, "Erreur de facturation")
        reversed_line = credit.invoice_line_ids.filtered(
            lambda l: l.clearance_category == 'debours')
        self.assertEqual(
            reversed_line.clearance_print_name,
            "Frais de manutention portuaire — Passage portuaire TC 40'")
        self.assertEqual(
            credit._clearance_designation(reversed_line),
            "Avoir — Frais de manutention portuaire — Passage portuaire TC 40'")

    def test_03_billing_maintains_the_alternative_names(self):
        Category = self.env['logistics.expense.category']
        Name = self.env['logistics.expense.category.name']
        Category.with_user(self.biller).browse(self.plain_category.id).write(
            {'alternative_name_ids': [(0, 0, {'name': "Frais de magasinage"}),
                                      (0, 0, {'name': "Frais de stockage"})]})
        self.assertEqual(self.plain_category.alternative_name_ids.mapped('name'),
                         ["Frais de magasinage", "Frais de stockage"],
                         "more than one name per category")
        with self.assertRaises(AccessError):
            Name.with_user(self.ops_agent).create(
                {'category_id': self.plain_category.id, 'name': "x"})
        with self.assertRaises(AccessError, msg="maintains names, not categories"):
            Category.with_user(self.biller).create(
                {'name': "New", 'code': "D-NEW"})
        arch = Category.with_user(self.biller).get_view(
            view_type='form')['arch']
        self.assertIn('name="alternative_name_ids"', arch)
        arch = self.env['logistics.billing.wizard'].with_user(
            self.biller).get_view()['arch']
        self.assertIn('name="alternative_name_id"', arch)

    # =================================================================
    # 16/10: the commission may be left off the invoice
    def test_10_the_biller_may_leave_the_commission_off_the_invoice(self):
        file = self._working_file()
        self._settled(file, amount=100000)
        file.customs_fee_amount = 30000
        file.action_close_operations()

        wizard = self._wizard(file, user=self.biller)
        self.assertFalse(wizard.skip_commission, "billed by default")
        self.assertEqual(wizard.commission_amount, 2000)
        wizard.skip_commission = True
        self.assertEqual(wizard.commission_amount, 0,
                         "ticked: nothing is charged for it")
        self.assertEqual(wizard.customs_fee_amount, 30000,
                         "the other revenue lines are untouched")
        wizard.action_create_invoice()
        self.assertTrue(file.billing_commission_skipped, "kept on the file")
        invoice = file.invoice_id.sudo()
        kinds = invoice.invoice_line_ids.mapped('clearance_service_kind')
        self.assertNotIn('commission', kinds, "no commission line at all")
        self.assertIn('customs_fee', kinds)
        self.assertEqual(
            sum(invoice.invoice_line_ids.filtered(
                lambda l: l.clearance_category == 'prestation'
            ).mapped('price_subtotal')), 30000)

    def test_11_the_commission_tick_survives_a_recharge_review(self):
        file = self._working_file()
        exp = self._settled(file, amount=100000)
        file.customs_fee_amount = 30000
        file.action_close_operations()

        wizard = self._wizard(file, user=self.biller)
        wizard.skip_commission = True
        line = wizard.debours_line_ids
        line.amount_recharged = 110000
        line.comment = "Agreed uplift"
        wizard.action_submit_for_review()
        self.assertTrue(file.billing_commission_skipped)
        file.with_user(self.ops_head).action_approve_recharge_ops()
        wizard = self._wizard(file, user=self.biller)
        self.assertTrue(wizard.skip_commission, "proposed again as ticked")
        self.assertEqual(wizard.commission_amount, 0)
        wizard.action_create_invoice()
        self.assertNotIn('commission', file.invoice_id.sudo()
                         .invoice_line_ids.mapped('clearance_service_kind'))
        self.assertEqual(exp.recharge_amount, 110000)

    # =================================================================
    # 2. the customer record is Customer Service's, complete before opening
    def test_04_a_file_is_not_opened_until_the_customer_record_is_complete(self):
        file = self._file(user=self.cs_agent, partner_id=self.bare_client.id)
        self.assertTrue(file.client_missing_details)
        self.assertIn("full name", file.client_missing_details)
        self.assertIn("Tax ID (NIU)", file.client_missing_details)
        with self.assertRaises(UserError) as caught:
            file.with_user(self.cs_agent).action_request_opening()
        self.assertIn("Customer Service", str(caught.exception))
        self.assertIn("Tax ID (NIU)", str(caught.exception))
        # Customer Service completes the record, and only they may
        self.bare_client.with_user(self.cs_agent).write({
            'clearance_invoice_name': "NKONGSAMBA NEGOCE SARL",
            'street': "BP 3 Nkongsamba", 'email': "negoce@test.cm",
            'vat': "M000000000081D",
            'company_registry': "RC/NKS/2026/B/0081"})
        self.assertFalse(file.client_missing_details)
        file.with_user(self.cs_agent).action_request_opening()
        self.assertEqual(file.opening_state, 'requested')
        file.with_user(self.cs_head).action_approve_opening()
        self.assertEqual(file.state, 'in_progress')

    def test_05_only_customer_service_changes_the_customer_record(self):
        for who in (self.biller, self.ops_agent, self.finance):
            with self.assertRaises(AccessError, msg=who.name):
                self.client.with_user(who).write({'street': "elsewhere"})
        self.client.with_user(self.cs_agent).write({'street': "BP 78 Douala"})
        self.assertEqual(self.client.street, "BP 78 Douala")
        self.assertTrue(self.cs_agent.has_group('base.group_partner_manager'))
        self.assertFalse(self.biller.has_group('base.group_partner_manager'))
        self.assertTrue(self.admin.has_group('base.group_partner_manager'))

    def test_06_the_billing_screen_reads_the_client_block(self):
        file = self._working_file()
        self._settled(file)
        file.action_close_operations()
        wizard = self._wizard(file, user=self.biller)
        self.assertEqual(wizard.client_name, "MBALMAYO BOIS ET DERIVES SA",
                         "filled from the customer record")
        self.assertEqual(wizard.client_vat, "M000000000071C")
        described = wizard.fields_get(['client_name', 'client_vat'])
        self.assertTrue(described['client_name']['readonly'])
        self.assertTrue(described['client_vat']['readonly'])
        arch = wizard.get_view()['arch']
        self.assertIn('name="client_name"', arch)
        self.assertNotIn('placeholder="e.g. CAPITAL', arch)

    def test_07_teese_history_is_exempt_from_the_customer_gate(self):
        file = self._file(partner_id=self.bare_client.id, legacy_id=990014,
                          state='imported')
        self.assertFalse(file.client_missing_details)
        file._check_client_complete()          # no error

    # =================================================================
    # 1. bilingual: the Administrator sets each user's language
    def _activate_french(self):
        """fr_FR with THIS module's terms only. Odoo's installer would
        load every installed module's French, which is minutes."""
        self.env['res.lang'].sudo()._activate_lang('fr_FR')
        module = self.env['ir.module.module'].sudo().search(
            [('name', '=', 'elite_clearance')])
        module._update_translations(['fr_FR'])

    def test_08_the_administrator_sets_a_users_language(self):
        self._activate_french()
        Wizard = self.env['clearance.user.language.wizard']
        wizard = Wizard.with_user(self.admin).create({})
        mine = wizard.line_ids.filtered(lambda l: l.user_id == self.cs_agent)
        self.assertTrue(mine, "every clearance user is listed")
        self.assertEqual(mine.lang, 'en_US')
        self.assertFalse(wizard.line_ids.filtered(
            lambda l: l.user_id == self.env.ref('base.user_root')),
            "root is not a clearance user")
        mine.lang = 'fr_FR'
        wizard.action_apply()
        self.assertEqual(self.cs_agent.lang, 'fr_FR')
        # the administrator is not Odoo's: the write went through the
        # wizard, not through a right on res.users
        self.assertFalse(self.admin.has_group('base.group_erp_manager'))
        with self.assertRaises(AccessError):
            self.cs_agent.with_user(self.admin).write({'lang': 'en_US'})
        # and the screen is the administrator's alone
        wizard = Wizard.with_user(self.admin).create({})
        wizard.line_ids.filtered(
            lambda l: l.user_id == self.ops_agent).lang = 'fr_FR'
        with self.assertRaises(AccessError):
            wizard.with_user(self.ops_head).action_apply()

    def test_09_the_screens_read_french_for_a_french_user(self):
        self._activate_french()
        self.cs_agent.sudo().lang = 'fr_FR'
        Expense = self.env['logistics.expense'].with_user(self.cs_agent)
        fields_fr = Expense.with_context(lang='fr_FR').fields_get(
            ['amount', 'state'])
        self.assertEqual(fields_fr['amount']['string'], "Montant")
        self.assertEqual(dict(fields_fr['state']['selection'])['draft'],
                         "Brouillon")
        fields_en = Expense.with_context(lang='en_US').fields_get(['amount'])
        self.assertEqual(fields_en['amount']['string'], "Amount",
                         "and English stays English")
        menu = self.env.ref('elite_clearance.menu_clearance_root')
        self.assertEqual(menu.with_context(lang='fr_FR').name, "Dédouanement")
        self.assertEqual(menu.with_context(lang='en_US').name, "Clearance")
