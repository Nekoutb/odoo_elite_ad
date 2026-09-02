from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExpensesAndBilling(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.oop_account = Account.create({
            'code': 'X4711', 'name': "Client Disbursements (OOP)",
            'account_type': 'asset_current', 'reconcile': True})
        cls.adv_account = Account.create({
            'code': 'X4712', 'name': "Employee Advances",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee_account = Account.create({
            'code': 'X7061', 'name': "Clearance Fee Income",
            'account_type': 'income'})
        cls.misc_journal = env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', company.id)], limit=1)
        if not cls.misc_journal:
            cls.misc_journal = env['account.journal'].create({
                'name': "Miscellaneous", 'type': 'general', 'code': 'XMSC'})
        company.write({
            'clearance_oop_account_id': cls.oop_account.id,
            'clearance_advance_account_id': cls.adv_account.id,
            'clearance_fee_account_id': cls.fee_account.id,
            'clearance_misc_journal_id': cls.misc_journal.id,
        })
        cls.momo_journal = env['account.journal'].create({
            'name': "Mobile Money", 'type': 'cash', 'code': 'XMOM'})
        cls.maviance_journal = env['account.journal'].create({
            'name': "Maviance", 'type': 'cash', 'code': 'XMAV'})
        cls.client = env['res.partner'].create({
            'name': "Billing Client SA", 'is_company': True})
        cls.customs = env['res.partner'].create({
            'name': "Douala Customs", 'is_company': True})
        cls.employee = env['hr.employee'].create({'name': "Field Declarant"})
        cls.category = env['logistics.expense.category'].create({
            'name': "Customs Duty", 'code': "T-DUTY"})
        cls.service = env['logistics.service.type'].create({
            'name': "Import test", 'code': "T-IMP2", 'commission_rate': 2.0})
        cls.file = env['logistics.file'].create({
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'

    def _expense(self, amount, mode='direct', journal=None):
        vals = {
            'file_id': self.file.id,
            'category_id': self.category.id,
            'description': "Duty on declaration",
            'amount': amount,
            'payment_mode': mode,
            'vendor_id': self.customs.id,
            'journal_id': (journal or self.momo_journal).id,
        }
        if mode == 'advance':
            vals['employee_id'] = self.employee.id
        return self.env['logistics.expense'].create(vals)

    def test_01_direct_expense_posts_oop_vs_journal(self):
        exp = self._expense(500000)
        exp.action_submit(); exp.action_approve(); exp.action_settle()
        self.assertEqual(exp.state, 'settled')
        move = exp.settlement_move_id
        self.assertEqual(move.state, 'posted')
        debit = move.line_ids.filtered(lambda l: l.debit > 0)
        credit = move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit.account_id, self.oop_account)
        self.assertEqual(credit.account_id, self.momo_journal.default_account_id)
        self.assertEqual(debit.debit, 500000)
        self.assertEqual(sum(move.line_ids.mapped('debit')),
                         sum(move.line_ids.mapped('credit')))
        # analytic tag = the file
        self.assertIn(str(self.file.analytic_account_id.id),
                      debit.analytic_distribution or {})
        self.assertEqual(self.file.oop_total, 500000)

    def test_02_advance_sits_on_employee_until_justified(self):
        exp = self._expense(200000, mode='advance', journal=self.maviance_journal)
        exp.action_submit(); exp.action_approve(); exp.action_settle()
        move = exp.settlement_move_id
        debit = move.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(debit.account_id, self.adv_account,
                         "Advance must hit the employee advances account.")
        self.assertEqual(debit.partner_id, self.employee.work_contact_id)
        self.assertEqual(self.file.oop_total, 0,
                         "Unjustified advance is employee debt, not OOP.")
        # justification refused without supporting documents
        with self.assertRaises(UserError):
            exp.action_justify()
        self.env['ir.attachment'].create({
            'name': "receipt.pdf", 'res_model': 'logistics.expense',
            'res_id': exp.id, 'raw': b"dummy"})
        exp.action_justify()
        self.assertEqual(exp.state, 'justified')
        jmove = exp.justification_move_id
        jd = jmove.line_ids.filtered(lambda l: l.debit > 0)
        jc = jmove.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(jd.account_id, self.oop_account)
        self.assertEqual(jc.account_id, self.adv_account)
        self.assertEqual(self.file.oop_total, 200000)

    def test_03_ops_close_blocked_by_pending_expense(self):
        exp = self._expense(100000)
        exp.action_submit()
        with self.assertRaises(UserError):
            self.file.action_close_operations()
        exp.action_approve(); exp.action_settle()
        self.file.action_close_operations()
        self.assertEqual(self.file.state, 'ops_closed')
        # no new expenses on a closed file
        with self.assertRaises(UserError):
            self._expense(1)

    def test_04_invoice_clears_oop_and_adds_fees(self):
        exp = self._expense(1000000)
        exp.action_submit(); exp.action_approve(); exp.action_settle()
        self.file.customs_fee_amount = 75000
        self.file.action_close_operations()
        self.assertEqual(self.file.commission_amount, 20000)  # 2% of 1,000,000
        self.file.action_create_invoice()
        inv = self.file.invoice_id
        self.assertEqual(inv.move_type, 'out_invoice')
        real = inv.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        oop_lines = real.filtered(lambda l: l.account_id == self.oop_account)
        fee_lines = real.filtered(lambda l: l.account_id == self.fee_account)
        self.assertEqual(sum(oop_lines.mapped('price_unit')), 1000000)
        self.assertEqual(sorted(fee_lines.mapped('price_unit')), [20000, 75000])
        # complete only after the invoice is posted
        with self.assertRaises(UserError):
            self.file.action_mark_complete()
        inv.action_post()
        # posted invoice credits OOP by the recharge amount
        oop_move_lines = inv.line_ids.filtered(
            lambda l: l.account_id == self.oop_account)
        self.assertEqual(sum(oop_move_lines.mapped('credit')), 1000000,
                         "The recharge section must clear the OOP account.")
        self.file.action_mark_complete()
        self.assertEqual(self.file.state, 'done')

    def test_05_reopen_requires_manager_and_reason(self):
        self.file.action_close_operations()
        wiz = self.env['logistics.file.reopen.wizard'].create({
            'file_id': self.file.id, 'reason': "Late port invoice received."})
        user = self.env['res.users'].create({
            'name': "Plain Ops", 'login': "plain.ops@test.example",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_user').id])]})
        with self.assertRaises(UserError):
            wiz.with_user(user).action_reopen()
        wiz.action_reopen()
        self.assertEqual(self.file.state, 'in_progress')
        self.assertEqual(self.file.reopen_count, 1)

    def test_06_settle_requires_finance_group(self):
        exp = self._expense(50000)
        exp.action_submit(); exp.action_approve()
        user = self.env['res.users'].create({
            'name': "Ops Only", 'login': "ops.only@test.example",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_user').id])]})
        with self.assertRaises(UserError):
            exp.with_user(user).action_settle()

    def test_07_reference_formats(self):
        """File refs are <year><code><0001…>; billing refs EL<yy><code><0001…>,
        sequenced independently per service type, no duplicates."""
        year = fields.Date.today().strftime("%Y")
        yy = fields.Date.today().strftime("%y")
        st_im = self.env['logistics.service.type'].create(
            {'name': "Import real", 'code': "IM", 'commission_rate': 2.0}) \
            if not self.env['logistics.service.type'].search(
                [('code', '=', 'IM')], limit=1) \
            else self.env['logistics.service.type'].search(
                [('code', '=', 'IM')], limit=1)
        f1 = self.env['logistics.file'].create({
            'partner_id': self.client.id, 'service_type_id': st_im.id})
        f2 = self.env['logistics.file'].create({
            'partner_id': self.client.id, 'service_type_id': st_im.id})
        self.assertTrue(f1.name.startswith(year + "IM"))
        self.assertEqual(int(f2.name[-4:]), int(f1.name[-4:]) + 1)
        self.assertNotEqual(f1.name, f2.name)
        # billing ref
        f1.state = 'in_progress'
        exp = self.env['logistics.expense'].create({
            'file_id': f1.id, 'category_id': self.category.id,
            'description': "Duty", 'amount': 100000,
            'payment_mode': 'direct', 'vendor_id': self.customs.id,
            'journal_id': self.momo_journal.id})
        exp.action_submit(); exp.action_approve(); exp.action_settle()
        f1.action_close_operations()
        f1.action_create_invoice()
        self.assertTrue(f1.invoice_id.name.startswith("EL" + yy + "IM"),
                        "Billing ref %s should be EL%sIM…" % (
                            f1.invoice_id.name, yy))
        f1.invoice_id.action_post()
        self.assertTrue(f1.invoice_id.name.startswith("EL" + yy + "IM"),
                        "Posting must keep the billing reference.")

    def test_08_master_data_seeded(self):
        """The four real service types and their checklists exist."""
        from odoo.addons.elite_clearance.hooks import seed_clearance_master_data
        seed_clearance_master_data(self.env)
        Service = self.env['logistics.service.type']
        for code, min_docs in (('IM', 10), ('BO', 8), ('ES', 5), ('AI', 11)):
            st = Service.search([('code', '=', code)], limit=1)
            self.assertTrue(st, "Service type %s missing." % code)
            self.assertGreaterEqual(len(st.document_ids), min_docs)
        cats = self.env['logistics.expense.category'].search_count(
            [('code', 'in', ['FBL', 'RTC', 'PHYT', 'PAD', 'XLEG'])])
        self.assertEqual(cats, 5, "Real expense categories missing.")
        # idempotent
        seed_clearance_master_data(self.env)
        self.assertEqual(Service.search_count([('code', '=', 'IM')]), 1)

    def test_09_configured_approvers_override_groups(self):
        """When approver lists are configured, group membership alone is no
        longer enough — and the configured user succeeds."""
        manager = self.env['res.users'].create({
            'name': "Manager A", 'login': "mgr.a@test.example",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_manager').id])]})
        chosen = self.env['res.users'].create({
            'name': "Chosen Approver", 'login': "chosen@test.example",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_user').id])]})
        self.env.company.clearance_expense_approver_ids = [(6, 0, [chosen.id])]
        exp = self._expense(10000)
        exp.action_submit()
        with self.assertRaises(UserError):
            exp.with_user(manager).action_approve()   # manager but not configured
        exp.with_user(chosen).action_approve()        # configured user wins
        self.assertEqual(exp.state, 'approved')

    def test_10_cancel_blocked_while_expenses_are_live(self):
        """Cancelling a working file would strand its expenses mid-flow."""
        exp = self._expense(300000)
        exp.action_submit()
        with self.assertRaises(UserError):
            self.file.action_cancel()
        exp.action_refuse()
        self.file.action_cancel()
        self.assertEqual(self.file.state, 'cancel')

    def test_11_cancel_blocked_once_the_invoice_is_posted(self):
        """Money has left the building: the correction is a credit note."""
        exp = self._expense(400000)
        exp.action_submit(); exp.action_approve(); exp.action_settle()
        self.file.action_close_operations()
        self.file.action_create_invoice()
        self.file.invoice_id.action_post()
        with self.assertRaises(UserError):
            self.file.action_cancel()
        self.assertEqual(self.file.state, 'ops_closed')

    def test_12_plain_user_cannot_cancel_a_working_file(self):
        """Cancelling past draft is an approver's decision."""
        user = self.env['res.users'].create({
            'name': "Ops Only 2", 'login': "ops.only2@test.example",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_user').id])]})
        with self.assertRaises(UserError):
            self.file.with_user(user).action_cancel()
        self.assertEqual(self.file.state, 'in_progress')

    def test_13_invoice_uses_the_configured_sales_journal(self):
        """Billing posts where the company says it should."""
        journal = self.env['account.journal'].create({
            'name': "Clearance Sales", 'type': 'sale', 'code': 'XCLS'})
        self.env.company.clearance_sale_journal_id = journal
        exp = self._expense(150000)
        exp.action_submit(); exp.action_approve(); exp.action_settle()
        self.file.action_close_operations()
        self.file.action_create_invoice()
        self.assertEqual(self.file.invoice_id.journal_id, journal)

    def test_14_expense_count_and_oop_total_are_independent(self):
        """The two file totals are computed separately: the counter includes
        every expense, the out-of-pocket total only what has actually landed
        on the client's account."""
        self._expense(60000)                       # draft — counted, not owed
        settled = self._expense(90000)
        settled.action_submit()
        settled.action_approve()
        settled.action_settle()
        self.file.invalidate_recordset(['expense_count', 'oop_total'])
        self.assertEqual(self.file.expense_count, 2)
        self.assertEqual(self.file.oop_total, 90000)
