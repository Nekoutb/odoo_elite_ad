from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStaffAdvances(TransactionCase):
    """Advances to staff: registration, the 421101 auxiliary, the
    reclassification to 47xx on justification, and the billing gate."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'X4711', 'name': "Debours engages (47xx)",
            'account_type': 'asset_current', 'reconcile': True})
        cls.advances = Account.create({
            'code': 'X421101', 'name': "Personnel debours avances",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'X7061', 'name': "Clearance Fee Income",
            'account_type': 'income'})
        cls.misc = env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', company.id)], limit=1)
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advances.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_misc_journal_id': cls.misc.id,
        })
        cls.journal = env['account.journal'].create({
            'name': "Mobile Money", 'type': 'cash', 'code': 'XMOM2'})
        cls.client = env['res.partner'].create({
            'name': "Advance Client SA", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Douala Port", 'is_company': True})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port charges", 'code': "T-PORT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Advance test", 'code': "T-ADV", 'commission_rate': 2.0})
        cls.employee = env['hr.employee'].create({'name': "Declarant Ndoh"})
        cls.file = env['logistics.file'].create({
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'
        cls.file.customs_fee_amount = 50000   # closing requires it keyed

    def _advance(self, amount, employee=None):
        return self.env['logistics.expense'].create({
            'file_id': self.file.id,
            'category_id': self.category.id,
            'description': "Terminal charges",
            'amount': amount,
            'payment_mode': 'advance',
            'vendor_id': self.vendor.id,
            'journal_id': self.journal.id,
            'employee_id': (employee or self.employee).id,
        })

    def _ops_manager(self, login):
        return self.env['res.users'].create({
            'name': "Ops Manager", 'login': login,
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_ops_manager').id])]})

    def _receipt(self, expense):
        return self.env['ir.attachment'].create({
            'name': "receipt.pdf", 'res_model': 'logistics.expense',
            'res_id': expense.id, 'raw': b"dummy"})

    # -- registration and the auxiliary --------------------------------
    def test_01_advance_needs_a_registered_staff_member(self):
        """No holder, no advance - refused at keying, not at settlement."""
        with self.assertRaises(ValidationError):
            self.env['logistics.expense'].create({
                'file_id': self.file.id,
                'category_id': self.category.id,
                'description': "Unattributed cash",
                'amount': 50000,
                'payment_mode': 'advance',
                'journal_id': self.journal.id,
            })

    def test_02_every_staff_member_gets_an_auxiliary(self):
        """Creating staff creates the contact that carries their 421101
        balance, even with nothing but a name keyed."""
        employee = self.env['hr.employee'].create({'name': "Fresh Hire"})
        self.assertTrue(
            employee.work_contact_id,
            "A staff member must have an auxiliary from creation.")
        self.assertEqual(employee.work_contact_id.name, "Fresh Hire")
        self.assertEqual(
            employee._clearance_auxiliary_partner(), employee.work_contact_id,
            "The helper must be idempotent, not create a second contact.")

    # -- the postings ---------------------------------------------------
    def test_03_advance_sits_on_421101_against_the_holder(self):
        exp = self._advance(300000)
        exp.action_submit()
        exp.action_approve(); exp.action_submit_settlement(); exp.action_approve_settlement()
        exp.action_settle()
        debit = exp.settlement_move_id.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(debit.account_id, self.advances)
        self.assertEqual(debit.partner_id, self.employee.work_contact_id,
                         "421101 must be auxiliarised to the holder.")
        self.assertEqual(self.file.oop_total, 0,
                         "An unjustified advance is not yet engaged.")
        self.assertEqual(self.file.unjustified_advance_total, 300000)
        self.assertEqual(self.employee.clearance_advance_balance, 300000)

    def test_04_justification_reclassifies_421101_to_47xx(self):
        exp = self._advance(250000)
        exp.action_submit()
        exp.action_approve(); exp.action_submit_settlement(); exp.action_approve_settlement()
        exp.action_settle()
        self._receipt(exp)
        exp.action_justify()
        move = exp.justification_move_id
        debit = move.line_ids.filtered(lambda l: l.debit > 0)
        credit = move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit.account_id, self.engaged)
        self.assertEqual(credit.account_id, self.advances)
        self.assertEqual(credit.partner_id, self.employee.work_contact_id,
                         "The reclassification must clear the same auxiliary.")
        self.assertEqual(self.file.unjustified_advance_total, 0)
        self.assertEqual(self.file.oop_total, 250000, "Now billable.")
        self.assertEqual(self.employee.clearance_advance_balance, 0)

    # -- the billing gate ------------------------------------------------
    def test_05_unjustified_advance_blocks_closing_and_billing(self):
        exp = self._advance(400000)
        exp.action_submit()
        exp.action_approve(); exp.action_submit_settlement(); exp.action_approve_settlement()
        exp.action_settle()
        with self.assertRaises(UserError):
            self.file.action_close_operations()
        self.assertEqual(self.file.state, 'in_progress')

    def test_06_waiver_needs_an_explanation_and_an_ops_manager(self):
        exp = self._advance(400000)
        exp.action_submit()
        exp.action_approve(); exp.action_submit_settlement(); exp.action_approve_settlement()
        exp.action_settle()
        with self.assertRaises(UserError):
            self.file.action_request_advance_waiver()   # no explanation
        self.file.advance_waiver_reason = "Holder on mission; receipts follow."
        self.file.action_request_advance_waiver()
        self.assertEqual(self.file.advance_waiver_state, 'requested')
        plain = self.env['res.users'].create({
            'name': "Plain Ops", 'login': "adv.plain@test.example",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_user').id])]})
        with self.assertRaises(UserError):
            self.file.with_user(plain).action_approve_advance_waiver()
        self.file.with_user(self._ops_manager("adv.ops@test.example")) \
            .action_approve_advance_waiver()
        self.assertEqual(self.file.advance_waiver_state, 'approved')

    def test_07_waiver_releases_the_file_but_never_the_money(self):
        """The point of the whole control: a waived file bills, but the
        unsupported advance is not recharged to the client."""
        justified = self._advance(600000)
        justified.action_submit()
        justified.action_approve(); justified.action_submit_settlement(); justified.action_approve_settlement()
        justified.action_settle()
        self._receipt(justified)
        justified.action_justify()

        stranded = self._advance(150000)
        stranded.action_submit()
        stranded.action_approve(); stranded.action_submit_settlement(); stranded.action_approve_settlement()
        stranded.action_settle()

        self.file.advance_waiver_reason = "Receipts lost; recovering by payroll."
        self.file.action_request_advance_waiver()
        self.file.with_user(self._ops_manager("adv.ops2@test.example")) \
            .action_approve_advance_waiver()

        self.file.action_close_operations()
        self.assertEqual(self.file.state, 'ops_closed')
        self.file.action_create_invoice()
        invoice = self.file.invoice_id
        recharged = invoice.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product'
            and l.account_id == self.engaged)
        self.assertEqual(sum(recharged.mapped('price_unit')), 600000,
                         "Only the justified advance may be recharged.")
        self.assertEqual(self.file.unjustified_advance_total, 150000)
        self.assertEqual(self.employee.clearance_advance_balance, 150000,
                         "The stranded advance stays the staff member's debt.")

    def test_08_refused_waiver_keeps_the_file_shut(self):
        exp = self._advance(90000)
        exp.action_submit()
        exp.action_approve(); exp.action_submit_settlement(); exp.action_approve_settlement()
        exp.action_settle()
        self.file.advance_waiver_reason = "Asking for an exception."
        self.file.action_request_advance_waiver()
        self.file.with_user(self._ops_manager("adv.ops3@test.example")) \
            .action_refuse_advance_waiver()
        self.assertEqual(self.file.advance_waiver_state, 'refused')
        with self.assertRaises(UserError):
            self.file.action_close_operations()
