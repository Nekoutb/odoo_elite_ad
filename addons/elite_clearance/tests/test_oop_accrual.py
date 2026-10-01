"""A disbursement is owed before it is paid.

Owner spec 01/10/2026. Approving a disbursement and naming the third
party recognises the debt: Dr Débours à engager / Cr the vendor. Paying
it clears the vendor against the money going out AND moves the debit
across to Débours engagés. Billing then recharges from there, as it
always did.

Switched on by naming the à-engager account. Without it the module posts
nothing until payment, exactly as before, and the second class in this
file proves that path is untouched.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


class AccrualCase(TransactionCase):
    """Fixture shared by the two-stage and the one-stage classes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'A47120', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.to_engage = Account.create({
            'code': 'A47110', 'name': "Debours a engager",
            'account_type': 'asset_current', 'reconcile': True})
        cls.payable = Account.create({
            'code': 'A40110', 'name': "Fournisseurs",
            'account_type': 'liability_payable', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'A70621', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'A65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'A75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales acc", 'type': 'sale', 'code': 'ASALA'})
        cls.misc = env['account.journal'].create({
            'name': "Misc acc", 'type': 'general', 'code': 'AMISA'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_commission_account_id': cls.fee.id,
            'clearance_service_fee_account_id': cls.fee.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_misc_journal_id': cls.misc.id,
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash acc", 'type': 'cash', 'code': 'ACSHA'})
        cls.client = env['res.partner'].create({
            'name': "Accrual Client", 'is_company': True,
            'street': "BP 1 Douala", 'email': "acc@test.cm",
            'vat': "M000000000061A",
            'company_registry': "RC/DLA/2026/B/0061",
            'clearance_invoice_name': "ACCRUAL CLIENT SARL"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal Accrual", 'is_company': True,
            'supplier_rank': 1,
            'property_account_payable_id': cls.payable.id})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port accrual", 'code': "A-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Accrual test", 'code': "A-ACC", 'commission_rate': 2.0})
        cls.employee = env['hr.employee'].create({'name': "Agent Accrual"})

    def setUp(self):
        super().setUp()
        self.file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUA000001",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': self.client.id,
            'service_type_id': self.service.id})
        self.file.state = 'in_progress'
        self.file.customs_fee_amount = 30000

    def _expense(self, amount=100000):
        return self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Handling", 'amount': amount})

    def _upto_settlement_submitted(self, amount=100000):
        exp = self._expense(amount)
        exp.action_submit()
        exp.action_approve()
        exp.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                   'vendor_id': self.vendor.id})
        exp.action_submit_settlement()
        return exp

    def _balance(self, account):
        """What the account carries across every posted entry."""
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id),
            ('parent_state', '=', 'posted')])
        return sum(lines.mapped('debit')) - sum(lines.mapped('credit'))


@tagged('post_install', '-at_install')
class TestOopAccrual(AccrualCase):
    """With the à-engager account named: the two-stage treatment."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.clearance_oop_payable_account_id = cls.to_engage.id

    def test_01_approving_it_recognises_what_is_owed(self):
        exp = self._upto_settlement_submitted()
        move = exp.accrual_move_id
        self.assertTrue(move, "the debt is recognised when it is owed")
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.journal_id, self.misc,
                         "no money has moved, so not the till's journal")
        self.assertEqual(move.logistics_file_id, self.file)

        debit = move.line_ids.filtered(lambda l: l.debit > 0)
        credit = move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit.account_id, self.to_engage)
        self.assertEqual(debit.debit, 100000)
        self.assertEqual(credit.account_id, self.payable, "credit the vendor")
        self.assertEqual(credit.credit, 100000)
        self.assertEqual(credit.partner_id, self.vendor,
                         "the vendor carries it in their own ledger")
        analytic = str(self.file.analytic_account_id.id)
        for line in move.line_ids:
            self.assertIn(analytic, line.analytic_distribution or {})

        self.assertEqual(self._balance(self.to_engage), 100000)
        self.assertEqual(self._balance(self.payable), -100000)
        self.assertEqual(self._balance(self.engaged), 0,
                         "nothing is engaged until it is paid")

    def test_02_paying_it_clears_the_vendor_and_moves_the_debit(self):
        exp = self._upto_settlement_submitted()
        exp.action_approve_settlement()
        exp.action_settle()

        move = exp.settlement_move_id
        self.assertTrue(move and move.state == 'posted')
        self.assertEqual(sum(move.line_ids.mapped('debit')),
                         sum(move.line_ids.mapped('credit')))

        self.assertEqual(self._balance(self.payable), 0,
                         "the vendor is paid and owed nothing")
        self.assertEqual(self._balance(self.to_engage), 0,
                         "nothing is waiting to be engaged any more")
        self.assertEqual(self._balance(self.engaged), 100000,
                         "it is engaged, and the client has not been billed")
        self.assertEqual(self._balance(self.cash.default_account_id), -100000,
                         "the money left the till")

    def test_03_billing_clears_what_was_engaged(self):
        exp = self._upto_settlement_submitted()
        exp.action_approve_settlement()
        exp.action_settle()
        self.file.action_close_operations()
        self.env['logistics.billing.wizard'].with_context(
            active_id=self.file.id).create({}).action_create_invoice()
        self.file.invoice_id.action_post()

        self.assertEqual(self._balance(self.engaged), 0,
                         "billed: 47xx clears in full")
        self.assertEqual(self._balance(self.to_engage), 0)
        self.assertEqual(self._balance(self.payable), 0)

    def test_04_the_three_stages_leave_only_the_client_owing(self):
        """End to end: the only thing left standing is the receivable."""
        exp = self._upto_settlement_submitted()
        exp.action_approve_settlement()
        exp.action_settle()
        self.file.action_close_operations()
        self.env['logistics.billing.wizard'].with_context(
            active_id=self.file.id).create({}).action_create_invoice()
        invoice = self.file.invoice_id
        invoice.action_post()
        receivable = invoice.line_ids.filtered(
            lambda l: l.display_type == 'payment_term')
        self.assertGreater(receivable.debit, 0)
        for account in (self.to_engage, self.engaged, self.payable):
            self.assertEqual(self._balance(account), 0, account.name)

    def test_05_refusing_it_unrecognises_the_debt(self):
        exp = self._upto_settlement_submitted()
        self.assertEqual(self._balance(self.to_engage), 100000)
        exp.action_return_settlement()
        exp.action_refuse()
        self.assertEqual(exp.state, 'cancel')
        self.assertEqual(self._balance(self.to_engage), 0,
                         "a refused disbursement owes nobody anything")
        self.assertEqual(self._balance(self.payable), 0)

    def test_06_a_recognised_disbursement_does_not_go_back_to_draft(self):
        exp = self._upto_settlement_submitted()
        exp.action_return_settlement()
        with self.assertRaises(UserError):
            exp.action_reset_to_draft()

    def test_07_a_staff_advance_is_untouched(self):
        """An advance has no third party and is owed to nobody: it keeps
        its own two-step treatment through 421101."""
        advance = self.env['account.account'].create({
            'code': 'A42110', 'name': "Personnel debours avances",
            'account_type': 'asset_receivable', 'reconcile': True})
        self.env.company.clearance_advance_account_id = advance.id
        exp = self._expense(40000)
        exp.action_submit()
        exp.action_approve()
        exp.write({'payment_mode': 'advance', 'journal_id': self.cash.id,
                   'employee_id': self.employee.id})
        exp.action_submit_settlement()
        self.assertFalse(exp.accrual_move_id,
                         "nothing is owed to a third party")
        self.assertEqual(self._balance(self.to_engage), 0)
        exp.action_approve_settlement()
        exp.action_settle()
        self.assertEqual(self._balance(advance), 40000,
                         "it stands against the holder, as it always did")


@tagged('post_install', '-at_install')
class TestOopWithoutAccrual(AccrualCase):
    """Without the account named: nothing posts until payment, as before."""

    def test_01_nothing_is_recognised_before_payment(self):
        self.assertFalse(self.env.company.clearance_oop_payable_account_id)
        exp = self._upto_settlement_submitted()
        self.assertFalse(exp.accrual_move_id)
        self.assertEqual(self._balance(self.engaged), 0)
        self.assertEqual(self._balance(self.payable), 0)

    def test_02_paying_it_posts_the_single_entry_it_always_did(self):
        exp = self._upto_settlement_submitted()
        exp.action_approve_settlement()
        exp.action_settle()
        self.assertEqual(self._balance(self.engaged), 100000)
        self.assertEqual(self._balance(self.payable), 0,
                         "recognised and settled in the same entry")
        self.assertEqual(self._balance(self.cash.default_account_id), -100000)
