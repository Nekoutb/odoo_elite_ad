"""Where the file sits, and closing it for good.

Owner spec 14/09/2026: a file says at the top whose desk it is on, so it
can be chased without anybody opening it; and a billed file can be closed
by the Billing Agent, after which only an Operations Manager can let
anybody back into it.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFileStageAndClose(TransactionCase):

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
        cls.fee = Account.create({
            'code': 'W70621', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'W65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'W75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales stage", 'type': 'sale', 'code': 'WSALS'})
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
            'name': "Cash stage", 'type': 'cash', 'code': 'WCSHS'})
        cls.client = env['res.partner'].create({
            'name': "Stage Client", 'is_company': True,
            'street': "BP 7 Douala", 'email': "stage@test.cm",
            'vat': "M000000000031A",
            'company_registry': "RC/DLA/2026/B/0031",
            'clearance_invoice_name': "STAGE CLIENT SARL"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal Stage", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port stage", 'code': "W-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Stage test", 'code': "W-STG", 'commission_rate': 2.0})

    def setUp(self):
        super().setUp()
        self.file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW000077",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': self.client.id,
            'service_type_id': self.service.id})
        self.file.customs_fee_amount = 30000

    def _expense(self, amount=50000):
        return self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Handling", 'amount': amount})

    # =================================================================
    # where it sits
    # =================================================================
    def test_01_a_draft_file_sits_with_whoever_opened_it(self):
        self.assertEqual(self.file.state, 'draft')
        self.assertEqual(self.file.stage_owner, self.file.create_uid.name)
        self.assertIn("Being opened", self.file.stage_detail)

    def test_02_the_stage_follows_the_money_through_its_approvals(self):
        self.file.state = 'in_progress'
        self.assertEqual(self.file.stage_detail, "Work in progress.")

        expense = self._expense()
        self.assertEqual(self.file.stage_detail, "Work in progress.",
                         "a draft disbursement is on nobody's desk yet")

        expense.action_submit()
        self.assertEqual(self.file.stage_owner, "Team Manager")
        self.assertIn("to approve", self.file.stage_detail)

        expense.action_approve()
        self.assertEqual(self.file.stage_owner, "Finance")
        self.assertIn("payment method", self.file.stage_detail)

        expense.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                       'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        self.assertEqual(self.file.stage_owner, "Finance Manager")
        self.assertIn("to sign", self.file.stage_detail)

        expense.action_approve_settlement()
        self.assertEqual(self.file.stage_owner, "Cashier",
                         "a cash journal is the till, not the bank")
        self.assertIn("to pay out", self.file.stage_detail)

        expense.action_settle()
        self.assertEqual(self.file.stage_detail, "Work in progress.",
                         "nothing is blocking any more")

    def test_03_after_operations_it_sits_with_billing_until_it_is_closed(self):
        self.file.state = 'in_progress'
        expense = self._expense()
        expense.action_submit()
        expense.action_approve()
        expense.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                       'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        self.file.action_close_operations()

        self.assertEqual(self.file.stage_owner, "Billing")
        self.assertIn("OK for billing", self.file.stage_detail)

        self.file.action_create_invoice()
        self.assertEqual(self.file.stage_owner, "Billing")
        self.assertIn("waiting to be posted", self.file.stage_detail)

        self.file.invoice_id.action_post()
        self.assertIn("can be closed", self.file.stage_detail)

        self.file.action_mark_complete()
        self.assertEqual(self.file.stage_owner, "Nobody")
        self.assertIn("Closed", self.file.stage_detail)

    def test_04_an_approval_on_the_file_names_who_owes_it(self):
        self.file.state = 'in_progress'
        self.file.write({'advance_waiver_state': 'requested'})
        self.assertEqual(self.file.stage_owner, "Operations Manager")
        self.assertIn("waiver", self.file.stage_detail)

    # =================================================================
    # closing it for good, and getting back in
    # =================================================================
    def _billed_and_closed(self):
        self.file.state = 'in_progress'
        expense = self._expense()
        expense.action_submit()
        expense.action_approve()
        expense.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                       'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        self.file.action_close_operations()
        self.file.action_create_invoice()
        self.file.invoice_id.action_post()
        self.file.action_mark_complete()
        return expense

    def test_05_closing_is_the_billers_call_and_reopening_is_not(self):
        self._billed_and_closed()
        self.assertEqual(self.file.state, 'done')
        self.assertTrue(self.file.date_closed)

        plain = self.env['res.users'].create({
            'name': "Plain Stage", 'login': "plain.stage@clearance.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_billing').id])]})
        wizard = self.env['logistics.file.reopen.wizard'].create({
            'file_id': self.file.id, 'target_state': 'ops_closed',
            'reason': "The client wants a second invoice."})
        with self.assertRaises(UserError,
                               msg="closing it was the biller's call; "
                                   "reopening it is not"):
            wizard.with_user(plain).action_reopen()

        ops = self.env['res.users'].create({
            'name': "Ops Mgr Stage", 'login': "ops.stage@clearance.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_ops_manager').id])]})
        wizard.with_user(ops).action_reopen()
        self.assertEqual(self.file.state, 'ops_closed')
        self.assertFalse(self.file.date_closed)

    def test_06_a_reopened_file_can_go_back_for_more_cost(self):
        self._billed_and_closed()
        self.env['logistics.file.reopen.wizard'].create({
            'file_id': self.file.id, 'target_state': 'in_progress',
            'reason': "The demurrage invoice arrived late."}).action_reopen()
        self.assertEqual(self.file.state, 'in_progress',
                         "back to operations, where a new cost can be keyed")
        self.assertEqual(self.file.reopen_count, 1)

    def test_07_what_was_billed_is_never_billed_again(self):
        expense = self._billed_and_closed()
        self.env['logistics.file.reopen.wizard'].create({
            'file_id': self.file.id, 'target_state': 'ops_closed',
            'reason': "Have another look at it."}).action_reopen()
        self.assertTrue(expense.is_billed)
        self.assertFalse(self.file._billable_expenses())
        self.assertFalse(self.file.has_billable)
        with self.assertRaises(UserError,
                               msg="the only way back to it is a credit note"):
            self.file.action_open_billing()
