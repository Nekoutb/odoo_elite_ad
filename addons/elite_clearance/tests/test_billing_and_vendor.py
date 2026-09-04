from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVendorPayableAndRecharge(TransactionCase):
    """Where a vendor payment lands, and what the client is charged for it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'X4715', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.advances = Account.create({
            'code': 'X421105', 'name': "Personnel debours avances",
            'account_type': 'asset_current', 'reconcile': True})
        cls.payable = Account.create({
            'code': 'X401100', 'name': "Suppliers",
            'account_type': 'liability_payable', 'reconcile': True})
        cls.commission = Account.create({
            'code': 'X70611', 'name': "Commission income", 'account_type': 'income'})
        cls.undercharge = Account.create({
            'code': 'X65811', 'name': "Debours undercharge",
            'account_type': 'expense'})
        cls.overcharge = Account.create({
            'code': 'X75811', 'name': "Debours overcharge",
            'account_type': 'income'})
        cls.service_fee = Account.create({
            'code': 'X70612', 'name': "Service fee income", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Clearance Sales", 'type': 'sale', 'code': 'XSAL5'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advances.id,
            'clearance_fee_account_id': cls.commission.id,
            'clearance_commission_account_id': cls.commission.id,
            'clearance_service_fee_account_id': cls.service_fee.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_oop_undercharge_account_id': cls.undercharge.id,
            'clearance_oop_overcharge_account_id': cls.overcharge.id,
        })
        cls.cash = env['account.journal'].create({
            'name': "Petty cash", 'type': 'cash', 'code': 'XCSH5'})
        cls.bank = env['account.journal'].create({
            'name': "Bank", 'type': 'bank', 'code': 'XBNK5'})
        cls.client = env['res.partner'].create({
            'name': "Recharge Client SA", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Maersk Cameroun", 'is_company': True, 'supplier_rank': 1})
        cls.vendor.property_account_payable_id = cls.payable
        cls.employee = env['hr.employee'].create({'name': "Field Agent R"})
        cls.category = env['logistics.expense.category'].create({
            'name': "Terminal", 'code': "T-TRM5"})
        cls.service = env['logistics.service.type'].create({
            'name': "Recharge test", 'code': "T-RCH", 'commission_rate': 2.0})
        cls.file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'
        cls.file.customs_fee_amount = 30000

        def user(name, group):
            return env['res.users'].create({
                'name': name, 'login': name.lower().replace(' ', '.') + "@rch.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.ops_manager = user("Ops Mgr B", 'ops_manager')
        cls.finance_manager = user("Fin Mgr B", 'finance_manager')
        cls.general_manager = user("Gen Mgr B", 'manager')
        cls.finance = user("Fin Clerk B", 'finance')

    def _settled(self, amount, mode='cash', vendor=True, journal=None):
        vals = {
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Terminal handling", 'amount': amount,
        }
        exp = self.env['logistics.expense'].create(vals)
        exp.action_submit()
        exp.action_approve()
        settlement = {'payment_mode': mode, 'journal_id': (journal or self.cash).id}
        settlement['vendor_id' if vendor else 'employee_id'] = (
            self.vendor.id if vendor else self.employee.id)
        exp.write(settlement)
        exp.action_submit_settlement()
        exp.action_approve_settlement()
        exp.action_settle()
        return exp

    # -- where a vendor payment lands -----------------------------------
    def test_01_a_vendor_payment_passes_through_the_vendor_payable(self):
        """The vendor's own payable account carries the charge and its
        settlement, so every third party has a ledger."""
        exp = self._settled(100000)
        move = exp.settlement_move_id
        self.assertEqual(move.state, 'posted')
        self.assertEqual(len(move.line_ids), 4, "47xx / 401100, then 401100 / cash")

        engaged = move.line_ids.filtered(lambda l: l.account_id == self.engaged)
        self.assertEqual(engaged.debit, 100000)
        payable = move.line_ids.filtered(lambda l: l.account_id == self.payable)
        self.assertEqual(len(payable), 2)
        self.assertEqual(sum(payable.mapped('debit')), 100000)
        self.assertEqual(sum(payable.mapped('credit')), 100000)
        self.assertEqual(payable.mapped('partner_id'), self.vendor,
                         "401100 is auxiliarised to the selected vendor")
        cash = move.line_ids.filtered(
            lambda l: l.account_id == self.cash.default_account_id)
        self.assertEqual(cash.credit, 100000, "the money still leaves today")
        self.assertEqual(sum(move.line_ids.mapped('debit')),
                         sum(move.line_ids.mapped('credit')))

    def test_02_an_advance_never_touches_the_vendor_payable(self):
        exp = self._settled(50000, mode='advance', vendor=False)
        move = exp.settlement_move_id
        self.assertEqual(len(move.line_ids), 2)
        self.assertFalse(move.line_ids.filtered(lambda l: l.account_id == self.payable))
        debit = move.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(debit.account_id, self.advances)

    def test_03_a_vendor_and_an_advance_holder_are_exclusive(self):
        """One counterparty per expense, enforced server-side and not only
        greyed out in the form."""
        exp = self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Both?", 'amount': 1000})
        with self.assertRaises(ValidationError):
            exp.write({'vendor_id': self.vendor.id,
                       'employee_id': self.employee.id})
        with self.assertRaises(ValidationError):
            exp.write({'payment_mode': 'advance', 'vendor_id': self.vendor.id})

    def test_04_the_payment_mode_is_cash_or_electronic(self):
        modes = dict(self.env['logistics.expense']._fields['payment_mode'].selection)
        self.assertEqual(set(modes), {'cash', 'electronic', 'advance'})
        exp = self._settled(20000, mode='electronic', journal=self.bank)
        self.assertEqual(exp.payment_mode, 'electronic')
        self.assertEqual(exp.state, 'settled')

    # -- justification now needs the Operations Manager -------------------
    def test_05_justification_is_approved_by_the_operations_manager(self):
        exp = self._settled(40000, mode='advance', vendor=False)
        self.env['ir.attachment'].create({
            'name': "receipt.pdf", 'res_model': 'logistics.expense',
            'res_id': exp.id, 'raw': b"dummy"})
        # attaching is not accepting: Finance submits, Operations decides
        with self.assertRaises(UserError):
            exp.action_justify()
        exp.action_submit_justification()
        self.assertEqual(exp.state, 'justification_submitted')
        self.assertTrue(exp.date_justification_submitted)
        with self.assertRaises(UserError):
            exp.with_user(self.finance).action_justify()
        exp.with_user(self.ops_manager).action_justify()
        self.assertEqual(exp.state, 'justified')
        self.assertTrue(exp.date_justified)
        self.assertTrue(exp.justification_move_id)

    def test_06_a_refused_justification_goes_back_to_finance(self):
        exp = self._settled(40000, mode='advance', vendor=False)
        self.env['ir.attachment'].create({
            'name': "receipt.pdf", 'res_model': 'logistics.expense',
            'res_id': exp.id, 'raw': b"dummy"})
        exp.action_submit_justification()
        exp.with_user(self.ops_manager).action_refuse_justification()
        self.assertEqual(exp.state, 'settled')
        self.assertFalse(exp.justification_move_id)
        self.assertEqual(self.file.unjustified_advance_total, 40000)

    # -- recharging at other than cost ------------------------------------
    def _closed_file_with(self, amount):
        self._settled(amount)
        self.file.action_close_operations()
        self.assertEqual(self.file.oop_total, amount)

    def _document(self):
        return self.env['ir.attachment'].create({
            'name': "client-agreement.pdf", 'res_model': 'logistics.file',
            'res_id': self.file.id, 'raw': b"dummy"})

    def test_07_changing_the_recharge_is_the_request(self):
        """No button: editing the figure puts the file into approval by
        itself, and billing is blocked until somebody signs."""
        self._closed_file_with(100000)
        self.assertEqual(self.file.recharge_state, 'none')
        self.file.recharge_amount = 120000
        self.assertEqual(self.file.recharge_state, 'requested',
                         "the edit itself must trigger the approval")
        self.assertEqual(self.file.recharge_variance, 20000)
        with self.assertRaises(UserError):
            self.file.action_create_invoice()
        self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.assertEqual(self.file.recharge_state, 'approved',
                         "above cost, Operations alone is enough")
        self.file.action_create_invoice()
        lines = self.file.invoice_id.invoice_line_ids
        recharged = lines.filtered(lambda l: l.account_id == self.engaged)
        self.assertEqual(sum(recharged.mapped('price_subtotal')), 100000,
                         "47xx always clears at cost")
        over = lines.filtered(lambda l: l.account_id == self.overcharge)
        self.assertEqual(over.price_subtotal, 20000)
        self.assertIn("overcharge", over.name)

    def test_07b_a_new_figure_tears_up_the_approval(self):
        self._closed_file_with(100000)
        self.file.recharge_amount = 120000
        self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.assertEqual(self.file.recharge_state, 'approved')
        self.file.recharge_amount = 130000
        self.assertEqual(self.file.recharge_state, 'requested',
                         "approval was given for a different number")
        self.assertFalse(self.file.recharge_ops_approved_by_id)
        # and putting it back to cost clears the whole thing
        self.file.recharge_amount = 0
        self.assertEqual(self.file.recharge_state, 'none')

    def test_08_below_cost_needs_a_reason_a_document_ops_and_the_gm(self):
        self._closed_file_with(100000)
        self.file.recharge_amount = 45000
        self.assertEqual(self.file.recharge_state, 'requested')
        self.assertEqual(self.file.recharge_variance, -55000)
        with self.assertRaises(UserError):
            self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.file.recharge_reason = "Commercial gesture agreed with the client."
        with self.assertRaises(UserError):
            self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self._document()
        self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.assertEqual(self.file.recharge_state, 'ops_approved',
                         "below cost, Operations is not enough on its own")
        with self.assertRaises(UserError):
            self.file.action_create_invoice()
        with self.assertRaises(UserError):
            self.file.with_user(self.finance).action_approve_recharge_gm()
        self.file.with_user(self.general_manager).action_approve_recharge_gm()
        self.assertEqual(self.file.recharge_state, 'approved')
        self.assertEqual(self.file.recharge_gm_approved_by_id, self.general_manager)
        self.file.action_create_invoice()
        lines = self.file.invoice_id.invoice_line_ids
        recharged = lines.filtered(lambda l: l.account_id == self.engaged)
        self.assertEqual(sum(recharged.mapped('price_subtotal')), 100000,
                         "47xx clears in full even when the client pays less")
        under = lines.filtered(lambda l: l.account_id == self.undercharge)
        self.assertEqual(under.price_subtotal, -55000,
                         "the shortfall is a cost, not a smaller recharge")
        self.assertIn("undercharge", under.name)
        self.assertEqual(
            sum(lines.filtered(lambda l: l.display_type == 'product')
                .mapped('price_subtotal')),
            45000 + 2000 + 30000,
            "the client is billed the approved recharge plus the fees")

    def test_09_no_adjustment_means_at_cost(self):
        self._closed_file_with(100000)
        self.assertEqual(self.file.recharge_state, 'none')
        self.file.action_create_invoice()
        recharged = self.file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.account_id == self.engaged)
        self.assertEqual(sum(recharged.mapped('price_subtotal')), 100000)

    def test_10_commission_and_service_fee_have_their_own_706_accounts(self):
        self._closed_file_with(100000)
        self.file.action_create_invoice()
        lines = self.file.invoice_id.invoice_line_ids
        commission = lines.filtered(lambda l: l.account_id == self.commission)
        service = lines.filtered(lambda l: l.account_id == self.service_fee)
        self.assertEqual(commission.price_subtotal, 2000, "2% of 100,000")
        self.assertEqual(service.price_subtotal, 30000, "the keyed customs fee")
        self.assertNotEqual(commission.account_id, service.account_id,
                            "the two revenue streams are reportable apart")
