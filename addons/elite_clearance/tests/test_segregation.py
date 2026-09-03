from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSegregationOfDuties(TransactionCase):
    """Who may do what to an expense, and who may close a file.

    The spending team keys; a team manager approves; Finance decides how
    it is paid; the Finance Manager signs that; the Operations Manager
    closes the file. Every step is a different pair of hands.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'X4713', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.advances = Account.create({
            'code': 'X421103', 'name': "Personnel debours avances",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'X7063', 'name': "Fee income", 'account_type': 'income'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advances.id,
            'clearance_fee_account_id': cls.fee.id,
        })
        cls.journal = env['account.journal'].create({
            'name': "Cash desk", 'type': 'cash', 'code': 'XCSH3'})
        cls.client = env['res.partner'].create({
            'name': "Segregation Client", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Port authority", 'is_company': True})
        cls.category = env['logistics.expense.category'].create({
            'name': "Handling", 'code': "T-HDL3"})
        cls.service = env['logistics.service.type'].create({
            'name': "Segregation test", 'code': "T-SEG"})
        cls.file = env['logistics.file'].create({
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'

        def user(name, *groups):
            return env['res.users'].create({
                'name': name, 'login': name.lower().replace(' ', '.') + "@seg.test",
                'group_ids': [(6, 0, [env.ref(g).id for g in groups])]})
        G = 'elite_clearance.group_clearance_'
        cls.plain = user("Plain Clearance", G + 'user')
        cls.ops = user("Ops Agent", G + 'operations')
        cls.cs_manager = user("CS Manager", G + 'customer_service_manager')
        cls.general_manager = user("General Manager", G + 'manager')
        cls.finance = user("Finance Clerk", G + 'finance')
        cls.finance_manager = user("Finance Manager", G + 'finance_manager')
        cls.ops_manager = user("Ops Manager", G + 'ops_manager')
        cls.cashier = user("Till Cashier", G + 'cashier')
        cls.treasury = user("Treasury Officer", G + 'treasury')

    def _vals(self, amount=100000):
        # What an originating team keys: the cost, and nothing about how it
        # will be paid.
        return {
            'file_id': self.file.id,
            'category_id': self.category.id,
            'description': "Handling at terminal",
            'amount': amount,
        }

    def _keyed_by_ops(self, amount=100000):
        return self.env['logistics.expense'].with_user(self.ops).create(
            self._vals(amount))

    # -- who keys ---------------------------------------------------------
    def test_01_finance_cannot_key_an_expense(self):
        with self.assertRaises(UserError):
            self.env['logistics.expense'].with_user(self.finance).create(
                self._vals())

    def test_02_plain_clearance_user_cannot_key_an_expense(self):
        """Being a clearance user is not being on a spending team."""
        with self.assertRaises(UserError):
            self.env['logistics.expense'].with_user(self.plain).create(
                self._vals())

    def test_03_operations_keys_and_submits_without_settlement_details(self):
        exp = self._keyed_by_ops()
        self.assertFalse(exp.payment_mode, "No mode until Finance sets it.")
        self.assertFalse(exp.journal_id)
        exp.with_user(self.ops).action_submit()
        self.assertEqual(exp.state, 'submitted')

    def test_04_originator_cannot_touch_the_settlement_fields(self):
        vals = self._vals()
        vals['payment_mode'] = 'cash'
        with self.assertRaises(UserError):
            self.env['logistics.expense'].with_user(self.ops).create(vals)
        exp = self._keyed_by_ops()
        with self.assertRaises(UserError):
            exp.with_user(self.ops).write({'journal_id': self.journal.id})
        with self.assertRaises(UserError):
            exp.with_user(self.ops).write({'vendor_id': self.vendor.id})

    # -- who approves -----------------------------------------------------
    def test_05_a_team_manager_approves_not_the_general_manager(self):
        exp = self._keyed_by_ops()
        exp.with_user(self.ops).action_submit()
        with self.assertRaises(UserError):
            exp.with_user(self.general_manager).action_approve()
        with self.assertRaises(UserError):
            exp.with_user(self.finance_manager).action_approve()
        exp.with_user(self.cs_manager).action_approve()
        self.assertEqual(exp.state, 'approved')

    # -- who pays ---------------------------------------------------------
    def test_06_finance_sets_the_settlement_and_the_finance_manager_signs(self):
        exp = self._keyed_by_ops()
        exp.with_user(self.ops).action_submit()
        exp.with_user(self.cs_manager).action_approve()
        # nothing can be settled on an unsigned settlement - even from the
        # superuser env, so it is the STATE that refuses, not the rights
        with self.assertRaises(UserError):
            exp.with_env(self.env).action_settle()
        # the Finance Manager cannot sign a blank settlement
        with self.assertRaises(UserError):
            exp.with_user(self.finance_manager).action_approve_settlement()
        exp.with_user(self.finance).write({
            'payment_mode': 'cash',
            'journal_id': self.journal.id,
            'vendor_id': self.vendor.id,
        })
        # the Finance Manager cannot sign what Finance has not sent on
        with self.assertRaises(UserError):
            exp.with_user(self.finance_manager).action_approve_settlement()
        exp.with_user(self.finance).action_submit_settlement()
        self.assertEqual(exp.state, 'settlement_submitted')
        # a Finance clerk proposes; only the Finance Manager signs
        with self.assertRaises(UserError):
            exp.with_user(self.finance).action_approve_settlement()
        exp.with_user(self.finance_manager).action_approve_settlement()
        self.assertEqual(exp.state, 'settlement_approved')
        # exp is still bound to the Ops agent env it was created under;
        # settle from the superuser env, as the other suites do
        exp = exp.with_env(self.env)
        exp.action_settle()
        self.assertEqual(exp.state, 'settled')
        self.assertEqual(
            exp.settlement_move_id.line_ids.filtered(lambda l: l.debit > 0).account_id,
            self.engaged)

    # -- who pays out -----------------------------------------------------
    def test_06b_cash_leaves_by_the_cashier_bank_by_treasury(self):
        """Money leaves through whoever holds it: the till by the Cashier,
        the bank by Treasury. A Finance clerk who is neither cannot pay."""
        bank = self.env['account.journal'].create({
            'name': "Bank", 'type': 'bank', 'code': 'XBNK3'})
        cash_exp, bank_exp = self._keyed_by_ops(70000), self._keyed_by_ops(80000)
        for exp, journal in ((cash_exp, self.journal), (bank_exp, bank)):
            exp.with_user(self.ops).action_submit()
            exp.with_user(self.cs_manager).action_approve()
            exp.with_user(self.finance).write({
                'payment_mode': 'cash' if journal.type == 'cash' else 'electronic',
                'journal_id': journal.id,
                'vendor_id': self.vendor.id})
            exp.with_user(self.finance).action_submit_settlement()
            exp.with_user(self.finance_manager).action_approve_settlement()
            self.assertEqual(exp.state, 'settlement_approved')
        # a Finance clerk holds neither the till nor the bank
        with self.assertRaises(UserError):
            cash_exp.with_user(self.finance).action_settle()
        # and neither may reach into the other's money
        with self.assertRaises(UserError):
            cash_exp.with_user(self.treasury).action_settle()
        with self.assertRaises(UserError):
            bank_exp.with_user(self.cashier).action_settle()
        # the right hands pass the check; the posting itself runs from the
        # superuser env, as every other suite does
        cash_exp.with_user(self.cashier)._check_disburser()
        bank_exp.with_user(self.treasury)._check_disburser()
        cash_exp.with_env(self.env).action_settle()
        bank_exp.with_env(self.env).action_settle()
        self.assertEqual(cash_exp.state, 'settled')
        self.assertEqual(bank_exp.state, 'settled')

    def test_06c_an_administrator_may_key_an_expense(self):
        """Admin sits in every group, Finance included, so the "Finance never
        keys" gate would lock the person configuring the system out of their
        own lab. Administrators configure; they do not operate."""
        admin = self.env.ref('base.user_admin')
        exp = self.env['logistics.expense'].with_user(admin).create(self._vals())
        self.assertEqual(exp.state, 'draft')

    # -- who closes -------------------------------------------------------
    def test_07_close_needs_the_customs_fee_and_an_operations_manager(self):
        self.assertFalse(self.file.customs_fee_amount)
        with self.assertRaises(UserError):
            self.file.action_close_operations()          # fee not keyed
        self.file.customs_fee_amount = 45000
        with self.assertRaises(UserError):
            self.file.with_user(self.plain).action_close_operations()
        with self.assertRaises(UserError):
            self.file.with_user(self.general_manager).action_close_operations()
        self.file.with_user(self.ops_manager).action_close_operations()
        self.assertEqual(self.file.state, 'ops_closed')
