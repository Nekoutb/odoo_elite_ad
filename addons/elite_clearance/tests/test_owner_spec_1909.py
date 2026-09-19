"""Owner spec 19/09/2026, second pass.

Who may name the third party on a disbursement, and how a receipt that
arrived on the bank journal is put against the file it belongs to.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec1909(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'T4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.outstanding = Account.create({
            'code': 'T5112', 'name': "Encaissements en cours",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'T70621', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'T65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'T75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales 1909", 'type': 'sale', 'code': 'TSAL9'})
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
            'name': "Cash 1909", 'type': 'cash', 'code': 'TCSH9'})
        cls.bank = env['account.journal'].create({
            'name': "Bank 1909", 'type': 'bank', 'code': 'TBNK9'})
        # Deterministic: a payment only makes a journal entry when it has
        # an outstanding account to make it against.
        method = cls.bank.inbound_payment_method_line_ids[:1]
        if method:
            method.payment_account_id = cls.outstanding.id

        def client(name):
            return env['res.partner'].create({
                'name': name, 'is_company': True,
                'street': "BP 19 Douala", 'email': "c1909@test.cm",
                'vat': "M000000000051A",
                'company_registry': "RC/DLA/2026/B/0051",
                'clearance_invoice_name': name.upper() + " SARL"})
        cls.client = client("Spec Client 1909")
        cls.other_client = client("Other Client 1909")
        cls.vendor = env['res.partner'].create({
            'name': "Terminal 1909", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port 1909", 'code': "T-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Spec 1909", 'code': "T-SPC", 'commission_rate': 2.0})

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@1909.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.agent = user("Ops Agent 1909", 'operations')
        cls.finance = user("Finance 1909", 'finance')

    def _file(self, partner=None):
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW001909",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': (partner or self.client).id,
            'service_type_id': self.service.id})
        file.state = 'in_progress'
        file.customs_fee_amount = 30000
        return file

    def _receipt(self, partner=None, amount=250000):
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': (partner or self.client).id,
            'amount': amount,
            'journal_id': self.bank.id,
        })
        payment.action_post()
        self.assertTrue(
            payment.move_id,
            "the bank journal must have an outstanding account, or a "
            "payment makes no entry at all")
        return payment

    # =================================================================
    # Who names the third party
    # =================================================================
    def test_01_the_third_party_is_finances_to_name(self):
        file = self._file()
        expense = self.env['logistics.expense'].with_user(self.agent).create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Handling", 'amount': 50000})
        self.assertEqual(self.env['logistics.expense']._fields[
            'vendor_id'].string, "Third Party")
        with self.assertRaises(UserError,
                               msg="the spending team does not name it"):
            expense.with_user(self.agent).vendor_id = self.vendor.id
        # back to the test user, who may approve; the agent may not
        expense = expense.sudo()
        expense.action_submit()
        expense.action_approve()
        expense.with_user(self.finance).write({
            'payment_mode': 'cash', 'journal_id': self.cash.id,
            'vendor_id': self.vendor.id})
        self.assertEqual(expense.vendor_id, self.vendor)

    def test_02_the_capture_dialog_does_not_offer_it(self):
        wizard = self.env['logistics.expense.capture.wizard']
        self.assertNotIn('vendor_id', wizard._fields,
                         "the originator is not asked who is paid")
        file = self._file()
        keyed = wizard.with_user(self.agent).with_context(
            active_id=file.id).create({
                'file_id': file.id, 'category_id': self.category.id,
                'description': "Keyed by the team", 'amount': 40000})
        keyed.action_submit_close()
        expense = file.expense_ids
        self.assertEqual(len(expense), 1)
        self.assertEqual(expense.state, 'submitted')
        self.assertFalse(expense.vendor_id)

    # =================================================================
    # A receipt on the bank journal, put against a file
    # =================================================================
    def test_03_a_customer_receipt_asks_which_file_it_is_for(self):
        payment = self._receipt()
        self.assertTrue(payment.clearance_needs_attribution)
        self.assertFalse(payment.logistics_file_id)
        action = payment.action_clearance_attribute()
        self.assertEqual(action['res_model'],
                         'logistics.payment.attribution.wizard')

    def test_04_the_dialog_shows_that_customers_open_files_and_no_others(self):
        mine_one = self._file()
        mine_two = self._file()
        theirs = self._file(self.other_client)
        closed = self._file()
        closed.state = 'done'
        payment = self._receipt()
        wizard = self.env['logistics.payment.attribution.wizard'].with_context(
            active_id=payment.id).create({})
        self.assertIn(mine_one, wizard.candidate_ids)
        self.assertIn(mine_two, wizard.candidate_ids)
        self.assertNotIn(theirs, wizard.candidate_ids,
                         "another customer's files are not shown")
        self.assertNotIn(closed, wizard.candidate_ids,
                         "a closed file takes no more advances")
        self.assertEqual(wizard.candidate_count, len(wizard.candidate_ids))

    def test_05_attributing_it_tags_the_entry_and_reaches_billing(self):
        file = self._file()
        payment = self._receipt(amount=250000)
        self.env['logistics.payment.attribution.wizard'].with_context(
            active_id=payment.id).create({
                'file_id': file.id}).action_attribute()

        self.assertEqual(payment.logistics_file_id, file)
        self.assertFalse(payment.clearance_needs_attribution)
        analytic = str(file.analytic_account_id.id)
        for line in payment.move_id.line_ids:
            self.assertIn(analytic, line.analytic_distribution or {},
                          "every line of the receipt carries the file")
        self.assertEqual(file._client_advances_in_the_ledger(), 250000)

        # and the billing screen reads it back with nothing typed
        expense = self.env['logistics.expense'].create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Handling", 'amount': 100000})
        expense.action_submit()
        expense.action_approve()
        expense.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                       'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        file.action_close_operations()
        wizard = self.env['logistics.billing.wizard'].with_context(
            active_id=file.id).create({})
        self.assertEqual(wizard.advance_other_amount, 250000)

    def test_06_a_receipt_can_be_moved_to_the_right_file(self):
        wrong = self._file()
        right = self._file()
        payment = self._receipt(amount=90000)
        Wizard = self.env['logistics.payment.attribution.wizard']
        Wizard.with_context(active_id=payment.id).create({
            'file_id': wrong.id}).action_attribute()
        self.assertEqual(wrong._client_advances_in_the_ledger(), 90000)

        Wizard.with_context(active_id=payment.id).create({
            'file_id': right.id}).action_attribute()
        self.assertEqual(payment.logistics_file_id, right)
        self.assertEqual(right._client_advances_in_the_ledger(), 90000)
        self.assertEqual(wrong._client_advances_in_the_ledger(), 0,
                         "the old file keeps none of it")

    def test_07_another_customers_file_is_refused(self):
        theirs = self._file(self.other_client)
        payment = self._receipt()
        wizard = self.env['logistics.payment.attribution.wizard'].with_context(
            active_id=payment.id).create({'file_id': theirs.id})
        with self.assertRaises(UserError) as caught:
            wizard.action_attribute()
        self.assertIn(self.other_client.name, str(caught.exception))
