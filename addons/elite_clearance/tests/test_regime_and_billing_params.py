from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRegimeAndBillingParams(TransactionCase):
    """The customs regime, the Billing department, and a billing screen
    that is the only place a billing parameter can be set."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'W4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.income = Account.create({
            'code': 'W7062', 'name': "Fees", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales", 'type': 'sale', 'code': 'WSAL'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.income.id,
            'clearance_commission_account_id': cls.income.id,
            'clearance_service_fee_account_id': cls.income.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash", 'type': 'cash', 'code': 'WCSH'})
        cls.client = env['res.partner'].create({
            'name': "Regime Client", 'is_company': True, 'street': "BP 1234 Douala", 'email': "client@test.cm", 'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal W", 'is_company': True, 'street': "BP 1234 Douala", 'email': "client@test.cm", 'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001", 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port", 'code': "W-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Regime test", 'code': "W-REG", 'commission_rate': 2.0})

    def _file(self, **extra):
        vals = {'partner_id': self.client.id,
                'service_type_id': self.service.id,
                'customs_regime': 'im4',
                'bl_awb_ref': "MEDUW000001",
                'goods_description': "Marchandises diverses",
                'cargo_value': 1000000.0}
        vals.update(extra)
        return self.env['logistics.file'].create(vals)

    def _billable_file(self):
        file = self._file()
        file.state = 'in_progress'
        expense = self.env['logistics.expense'].create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Handling", 'amount': 100000,
            'unit_label': "Par Conteneur"})
        expense.action_submit()
        expense.action_approve()
        expense.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                       'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        file.action_close_operations()
        return file

    def _wizard(self, file):
        return self.env['logistics.billing.wizard'].with_context(
            active_id=file.id).create({})

    # --- the customs regime --------------------------------------------
    def test_01_a_file_cannot_be_opened_without_a_regime(self):
        """Everything else supplied, so the regime is the only thing left."""
        with self.assertRaises(ValidationError):
            self.env['logistics.file'].create({
                'partner_id': self.client.id,
                'service_type_id': self.service.id,
                'bl_awb_ref': "MEDUW000001",
                'goods_description': "Marchandises diverses",
                'cargo_value': 1000000.0})

    def test_02_the_four_regimes_are_the_only_choices(self):
        keys = dict(self.env['logistics.file']._fields['customs_regime']
                    .selection).keys()
        self.assertEqual(set(keys), {'im4', 'im5', 'im7', 'im8'})

    def test_03_work_cannot_start_without_one(self):
        file = self._file()
        file.invalidate_recordset()
        self.env.cr.execute(
            "UPDATE logistics_file SET customs_regime = NULL WHERE id = %s",
            (file.id,))
        file.invalidate_recordset()
        with self.assertRaises(UserError):
            file.action_start_work()

    def test_04_imported_history_is_exempt(self):
        """Teese files have no IM regime and inventing one would be worse."""
        file = self._file()
        file.state = 'imported'
        file.customs_regime = False
        file.flush_recordset()
        self.assertFalse(file.customs_regime)

    # --- the Billing department -----------------------------------------
    def test_05_the_new_roles_exist_and_nest(self):
        ref = self.env.ref
        agent = ref('elite_clearance.group_clearance_billing')
        manager = ref('elite_clearance.group_clearance_billing_manager')
        self.assertEqual(agent.name, "Billing Agent")
        self.assertEqual(manager.name, "Billing Manager")
        self.assertIn(agent, manager.implied_ids,
                      "a Billing Manager is also a Billing Agent")

    def test_06_the_departments_are_named_as_the_owner_named_them(self):
        expected = {
            'group_clearance_finance': "Finance Agent",
            'group_clearance_finance_manager': "Finance Manager",
            'group_clearance_cashier': "Cashier",
            'group_clearance_operations': "Operations Agent",
            'group_clearance_ops_manager': "Operations Manager",
            'group_clearance_customer_service': "Customer Service Agent",
            'group_clearance_customer_service_manager': "Customer Service Manager",
            'group_clearance_transit': "Transit Agent",
            'group_clearance_transit_manager': "Transit Manager",
        }
        for xmlid, label in expected.items():
            self.assertEqual(
                self.env.ref('elite_clearance.' + xmlid).name, label, xmlid)

    # --- billing parameters live in the dialog, nowhere else ------------
    def test_07_the_screen_proposes_the_rate_and_the_fee(self):
        file = self._billable_file()
        wizard = self._wizard(file)
        self.assertEqual(wizard.commission_rate, 2.0,
                         "proposed from the service type")
        self.assertEqual(wizard.commission_amount, 2000)

    def test_08_the_agent_may_change_the_rate(self):
        file = self._billable_file()
        wizard = self._wizard(file)
        wizard.commission_rate = 5.0
        self.assertEqual(wizard.commission_amount, 5000)
        wizard.customs_fee_amount = 40000
        self.assertEqual(wizard.service_total, 5000 + 40000)
        wizard.action_create_invoice()
        self.assertEqual(file.billing_commission_rate, 5.0,
                         "the rate actually billed is kept on the file")
        self.assertEqual(file.customs_fee_amount, 40000)

    def test_09_the_rate_change_does_not_leak_to_other_files(self):
        """A rate is a decision about ONE invoice, not about the service."""
        file = self._billable_file()
        wizard = self._wizard(file)
        wizard.commission_rate = 7.5
        wizard.action_create_invoice()
        self.assertEqual(self.service.commission_rate, 2.0,
                         "the service type keeps its own rate")

    def test_10_the_printed_invoice_groups_debours_and_prestations(self):
        file = self._billable_file()
        self._wizard(file).action_create_invoice()
        lines = file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product')
        debours = lines.filtered(lambda l: l.clearance_category == 'debours')
        prestations = lines.filtered(
            lambda l: l.clearance_category == 'prestation')
        self.assertTrue(debours)
        self.assertTrue(prestations)
        self.assertEqual(debours.clearance_unit, "Par Conteneur",
                         "the unit follows the expense onto the invoice")

    def test_11_the_invoice_prints(self):
        file = self._billable_file()
        file.write({'bl_awb_ref': "MEDUW1", 'client_reference': "REF-1",
                    'supplier_name': "SHANDONG", 'goods_description': "CAPS",
                    'container_count': 1, 'container_type': "40",
                    'package_count': 865, 'weight_kg': 14367})
        self._wizard(file).action_create_invoice()
        html = self.env['ir.actions.report']._render_qweb_html(
            'elite_clearance.report_clearance_invoice',
            file.invoice_id.ids)[0]
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("Facture doit", "N° BL/N° LTA", "Catégorie",
                         "Désignation", "Debours", "Prestations",
                         "TOTAL HT", "TOTAL TTC", "RESTE",
                         "MEDUW1", "SHANDONG", "Par Conteneur"):
            self.assertIn(expected, text, expected)

    def test_12_advances_come_off_the_balance_due(self):
        file = self._billable_file()
        wizard = self._wizard(file)
        wizard.advance_had_amount = 20000
        wizard.advance_had_vat_amount = 3850
        wizard.action_create_invoice()
        self.assertEqual(file.advance_had_amount, 20000)
        self.assertEqual(
            file.invoice_balance_due,
            file.invoice_id.amount_total - 23850)

    # --- a new revenue line is Operations' decision ---------------------
    def test_13_a_new_service_cannot_be_billed_until_approved(self):
        service = self.env['logistics.billing.service'].create({
            'name': "Frais d'ouverture de dossier", 'default_amount': 20964,
            'account_id': self.income.id})
        self.assertEqual(service.state, 'draft')
        domain = str(self.env['logistics.billing.wizard.service']._fields[
            'service_id'].domain)
        self.assertIn("'approved'", domain,
                      "only approved services can be picked")

    def test_14_the_operations_manager_approves_it(self):
        ops = self.env['res.users'].create({
            'name': "Ops W", 'login': "ops.w@rg.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_ops_manager').id])]})
        biller = self.env['res.users'].create({
            'name': "Bill W", 'login': "bill.w@rg.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_billing').id])]})
        service = self.env['logistics.billing.service'].with_user(
            biller).create({'name': "Frais de dossier W",
                            'default_amount': 15000})
        with self.assertRaises(UserError):
            service.with_user(biller).action_approve()
        service.with_user(ops).action_approve()
        self.assertEqual(service.state, 'approved')
        self.assertEqual(service.approved_by_id, ops)

    def test_15_an_approved_service_can_then_be_billed(self):
        service = self.env['logistics.billing.service'].create({
            'name': "Frais de dossier X", 'default_amount': 20964,
            'account_id': self.income.id, 'unit_label': "Par dossier"})
        service.action_approve()
        file = self._billable_file()
        wizard = self._wizard(file)
        wizard.service_line_ids = [(0, 0, {
            'service_id': service.id, 'name': service.name,
            'amount': service.default_amount,
            'account_id': service.account_id.id})]
        wizard.action_create_invoice()
        line = file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.name == "Frais de dossier X")
        self.assertEqual(line.price_subtotal, 20964)
        self.assertEqual(line.clearance_category, 'prestation')

    def test_16_a_proposed_service_waits_in_the_ops_manager_queue(self):
        ops = self.env['res.users'].create({
            'name': "Ops Y", 'login': "ops.y@rg.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_ops_manager').id])]})
        service = self.env['logistics.billing.service'].create({
            'name': "Frais de dossier Y", 'default_amount': 9000})
        task = self.env['clearance.task'].with_user(ops).search(
            [('kind', '=', 'billing_service'), ('res_id', '=', service.id)])
        self.assertTrue(task, "Operations should be asked to approve it")
        service.action_approve()
        self.assertFalse(self.env['clearance.task'].with_user(ops).search(
            [('kind', '=', 'billing_service'), ('res_id', '=', service.id)]),
            "and it leaves the queue once approved")


@tagged('post_install', '-at_install')
class TestInvoiceEssentials(TransactionCase):
    """What the printed invoice needs, demanded when the file is opened."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.complete = env['res.partner'].create({
            'name': "Complete Client", 'is_company': True,
            'street': "BP 18302 Douala", 'email': "c@test.cm",
            'vat': "M000000000009A", 'company_registry': "RC/DLA/2026/B/9"})
        cls.bare = env['res.partner'].create({
            'name': "Bare Client", 'is_company': True})
        cls.service = env['logistics.service.type'].create({
            'name': "Essentials", 'code': "X-ESS"})

    def _vals(self, partner=None, **extra):
        vals = {'partner_id': (partner or self.complete).id,
                'service_type_id': self.service.id,
                'customs_regime': 'im4',
                'bl_awb_ref': "MEDUW000001",
                'goods_description': "Marchandises diverses",
                'cargo_value': 1000000.0}
        vals.update(extra)
        return vals

    def test_01_a_complete_file_opens(self):
        file = self.env['logistics.file'].create(self._vals())
        self.assertTrue(file.name)

    def test_02_each_missing_field_is_refused(self):
        for field in ('bl_awb_ref', 'goods_description', 'cargo_value'):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.env['logistics.file'].create(
                        self._vals(**{field: False}))

    def test_03_the_client_must_carry_what_the_invoice_prints(self):
        """No address, e-mail, NIU or RC on the client: no file."""
        with self.assertRaises(ValidationError):
            self.env['logistics.file'].create(self._vals(partner=self.bare))

    def test_04_everything_missing_is_named_at_once(self):
        """One list, not four rounds of trial and error."""
        try:
            self.env['logistics.file'].create(self._vals(
                partner=self.bare, bl_awb_ref=False,
                goods_description=False, cargo_value=0.0))
        except ValidationError as error:
            message = str(error)
        else:
            self.fail("an empty file must be refused")
        for expected in ("BL", "Produits", "Valeur RVC",
                         "postal address", "e-mail", "Tax ID", "Company ID"):
            self.assertIn(expected, message, expected)

    def test_05_imported_history_is_exempt(self):
        """Teese files predate the rule and must not be blocked by it."""
        file = self.env['logistics.file'].with_context(
            legacy_import=True).create({
                'partner_id': self.bare.id,
                'service_type_id': self.service.id})
        self.assertTrue(file.name)
