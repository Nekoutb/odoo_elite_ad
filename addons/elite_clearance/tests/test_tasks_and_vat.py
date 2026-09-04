from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTasksAndVat(TransactionCase):
    """One task queue per role, and VAT that lands only on the fees."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'Z4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.commission = Account.create({
            'code': 'Z70621', 'name': "Commission", 'account_type': 'income'})
        cls.service_fee = Account.create({
            'code': 'Z70622', 'name': "HAD", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales", 'type': 'sale', 'code': 'ZSAL'})
        cls.vat = env['account.tax'].create({
            'name': "TVA 19.25%", 'amount': 19.25, 'amount_type': 'percent',
            'type_tax_use': 'sale',
        })
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.commission.id,
            'clearance_commission_account_id': cls.commission.id,
            'clearance_service_fee_account_id': cls.service_fee.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_service_tax_ids': [(6, 0, cls.vat.ids)],
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash", 'type': 'cash', 'code': 'ZCSH'})
        cls.client = env['res.partner'].create({
            'name': "VAT Client", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port", 'code': "Z-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "VAT test", 'code': "Z-VAT", 'commission_rate': 2.0})
        cls.file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'
        cls.file.customs_fee_amount = 30000

        expense = env['logistics.expense'].create({
            'file_id': cls.file.id, 'category_id': cls.category.id,
            'description': "Handling", 'amount': 100000})
        expense.action_submit()
        expense.action_approve()
        expense.write({'payment_mode': 'cash', 'journal_id': cls.cash.id,
                       'vendor_id': cls.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        cls.expense = expense

    def _user(self, name, group):
        return self.env['res.users'].create({
            'name': name, 'login': name.lower().replace(' ', '.') + "@tq.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.' + group).id])]})

    # --- VAT ----------------------------------------------------------
    def test_01_vat_lands_on_the_services_and_not_the_debours(self):
        self.file.action_close_operations()
        self.file.action_create_invoice()
        invoice = self.file.invoice_id
        debours = invoice.invoice_line_ids.filtered(
            lambda l: l.account_id == self.engaged)
        self.assertTrue(debours)
        self.assertFalse(debours.tax_ids,
                         "a disbursement is the client's own liability")
        fees = invoice.invoice_line_ids.filtered(
            lambda l: l.account_id in (self.commission, self.service_fee))
        self.assertTrue(fees)
        for line in fees:
            self.assertEqual(line.tax_ids, self.vat,
                             "%s should carry the configured VAT" % line.name)

    def test_02_the_invoice_totals_carry_the_tax(self):
        self.file.action_close_operations()
        self.file.action_create_invoice()
        invoice = self.file.invoice_id
        # commission 2% of 100,000 plus the 30,000 customs fee
        self.assertEqual(invoice.amount_untaxed, 100000 + 2000 + 30000)
        self.assertAlmostEqual(invoice.amount_tax, 32000 * 0.1925, places=2)

    def test_03_no_vat_configured_means_no_vat_charged(self):
        self.env.company.clearance_service_tax_ids = [(5, 0, 0)]
        self.file.action_close_operations()
        self.file.action_create_invoice()
        invoice = self.file.invoice_id
        self.assertEqual(invoice.amount_tax, 0)
        self.assertFalse(invoice.invoice_line_ids.mapped('tax_ids'))

    def test_04_the_billing_screen_shows_the_tax_it_will_charge(self):
        self.file.action_close_operations()
        wizard = self.env['logistics.billing.wizard'].with_context(
            active_id=self.file.id).create({})
        self.assertEqual(wizard.service_total, 32000)
        self.assertAlmostEqual(wizard.service_tax_total, 32000 * 0.1925,
                               places=2)
        self.assertAlmostEqual(
            wizard.invoice_total, 100000 + 32000 + 32000 * 0.1925, places=2)

    # --- the task queue ------------------------------------------------
    def test_05_a_task_appears_for_the_role_that_can_act(self):
        """The file is in progress, so it is the Ops Manager's to close."""
        ops = self._user("Ops Q", 'group_clearance_ops_manager')
        tasks = self.env['clearance.task'].with_user(ops).search([])
        closing = tasks.filtered(lambda t: t.kind == 'ops_close')
        self.assertTrue(closing, "the Ops Manager should see a file to close")
        self.assertEqual(closing.res_model, 'logistics.file')
        self.assertEqual(closing.res_id, self.file.id)
        self.assertEqual(closing.partner_id, self.client)

    def test_06_a_role_never_sees_a_queue_it_cannot_act_on(self):
        """The whole point of one screen: it is a different screen each."""
        ops = self._user("Ops R", 'group_clearance_ops_manager')
        cashier = self._user("Cash R", 'group_clearance_cashier')
        ops_kinds = set(self.env['clearance.task'].with_user(ops)
                        .search([]).mapped('kind'))
        cashier_kinds = set(self.env['clearance.task'].with_user(cashier)
                            .search([]).mapped('kind'))
        self.assertIn('ops_close', ops_kinds)
        self.assertNotIn('ops_close', cashier_kinds,
                         "a cashier does not close files for operations")
        self.assertNotIn('disburse_cash', ops_kinds,
                         "and an Ops Manager does not pay out cash")

    def test_07_the_queue_follows_the_record_through_its_states(self):
        finance = self._user("Bill S", 'group_clearance_billing')
        Task = self.env['clearance.task']

        def kinds_for(user):
            return set(Task.with_user(user).search([]).mapped('kind'))

        self.assertNotIn('billing', kinds_for(finance),
                         "nothing to bill while the file is in progress")
        self.file.action_close_operations()
        self.assertIn('billing', kinds_for(finance),
                      "closing for operations puts it in Billing's queue")
        self.file.action_create_invoice()
        self.assertNotIn('billing', kinds_for(finance),
                         "and billing it takes it back out")

    def test_08_opening_a_task_goes_to_the_real_record(self):
        ops = self._user("Ops T", 'group_clearance_ops_manager')
        task = self.env['clearance.task'].with_user(ops).search(
            [('kind', '=', 'ops_close')], limit=1)
        action = task.action_open()
        self.assertEqual(action['res_model'], 'logistics.file')
        self.assertEqual(action['res_id'], self.file.id)

    def test_09_an_expense_task_carries_its_own_detail(self):
        """A second expense, left waiting, shows up with its description."""
        expense = self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Crane hire", 'amount': 45000})
        expense.action_submit()
        ops = self._user("Ops U", 'group_clearance_ops_manager')
        task = self.env['clearance.task'].with_user(ops).search(
            [('kind', '=', 'expense_approve'),
             ('res_id', '=', expense.id)], limit=1)
        self.assertTrue(task)
        self.assertEqual(task.detail, "Crane hire")
        self.assertEqual(task.amount, 45000)
        self.assertEqual(task.file_id, self.file)

    def test_10_cash_and_bank_disbursements_are_different_queues(self):
        bank = self.env['account.journal'].create({
            'name': "Bank", 'type': 'bank', 'code': 'ZBNK'})
        by_cash = self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Petty", 'amount': 5000})
        by_bank = self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Transfer", 'amount': 7000})
        for expense, journal in ((by_cash, self.cash), (by_bank, bank)):
            expense.action_submit()
            expense.action_approve()
            expense.write({'payment_mode': 'cash' if journal == self.cash
                           else 'electronic',
                           'journal_id': journal.id,
                           'vendor_id': self.vendor.id})
            expense.action_submit_settlement()
            expense.action_approve_settlement()

        cashier = self._user("Cash V", 'group_clearance_cashier')
        treasury = self._user("Treas V", 'group_clearance_treasury')
        Task = self.env['clearance.task']
        cash_ids = Task.with_user(cashier).search(
            [('kind', '=', 'disburse_cash')]).mapped('res_id')
        bank_ids = Task.with_user(treasury).search(
            [('kind', '=', 'disburse_bank')]).mapped('res_id')
        self.assertIn(by_cash.id, cash_ids)
        self.assertNotIn(by_bank.id, cash_ids,
                         "the cashier does not pay a bank transfer")
        self.assertIn(by_bank.id, bank_ids)
        self.assertNotIn(by_cash.id, bank_ids)
