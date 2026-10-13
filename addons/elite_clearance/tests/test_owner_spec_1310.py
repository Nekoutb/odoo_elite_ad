"""Owner spec 13/10/2026: who collects the cash is named by the requester
and is administrative - the advance stands against the requester whoever
collected it - and the transit order stays Customer Service's to change
once work has started."""

from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec1310(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'C4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.advances = Account.create({
            'code': 'C421101', 'name': "Personnel debours avances",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'C70621', 'name': "Fees", 'account_type': 'income'})
        cls.misc = env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', company.id)], limit=1)
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advances.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_misc_journal_id': cls.misc.id,
        })
        cls.till = env['account.journal'].create({
            'name': "Caisse 1310", 'type': 'cash', 'code': 'CCSH'})
        cls.client = env['res.partner'].create({
            'name': "Sotrafic", 'is_company': True,
            'street': "BP 44 Douala", 'email': "sotrafic@test.cm",
            'vat': "M000000000071C", 'company_registry': "RC/DLA/2026/B/0071",
            'clearance_invoice_name': "SOTRAFIC CAMEROUN SA"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal Douala", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Frais de port", 'code': "C-PORT",
            'justification': 'justifiable'})
        cls.service = env['logistics.service.type'].create({
            'name': "Spec 1310", 'code': "C-SPC", 'commission_rate': 2.0})

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@1310.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.cs_agent = user("Marthe Ebanda", 'customer_service')
        cls.cs_head = user("CS Head C", 'customer_service_manager')
        cls.ops_agent = user("Ops Agent C", 'operations')
        cls.courier = user("Courier C", 'operations')
        cls.ops_head = user("Ops Head C", 'ops_manager')
        cls.finance = user("Finance C", 'finance')
        cls.finance_head = user("Finance Head C", 'finance_manager')
        cls.cashier = user("Cashier C", 'cashier')
        # the requester and a colleague who may fetch the cash; the
        # Customer Service agent deliberately has no employee record
        cls.requester_emp = env['hr.employee'].create({
            'name': "Ops Agent C", 'user_id': cls.ops_agent.id})
        cls.courier_emp = env['hr.employee'].create({
            'name': "Courier C", 'user_id': cls.courier.id})

    # -----------------------------------------------------------------
    def _file(self, user=None, **extra):
        File = self.env['logistics.file']
        if user:
            File = File.with_user(user)
        vals = {
            'customs_regime': 'im4', 'bl_awb_ref': "MEDUC000131",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0, 'partner_id': self.client.id,
            'service_type_id': self.service.id}
        vals.update(extra)
        return File.create(vals)

    def _working_file(self):
        file = self._file()
        file.state = 'in_progress'
        return file

    def _capture(self, file, user=None, **vals):
        """Key a disbursement through the dialog, as the requester."""
        user = user or self.ops_agent
        keyed = {'category_id': self.category.id,
                 'description': "Manutention", 'amount': 25000,
                 'journal_id': self.till.id}
        keyed.update(vals)
        wizard = self.env['logistics.expense.capture.wizard'].with_user(
            user).with_context(active_id=file.id).create(keyed)
        before = file.expense_ids
        wizard.action_submit_close()
        return (file.expense_ids - before).with_env(self.env)

    def _paid(self, exp):
        """The head approves, Finance prepares and signs, the cashier
        pays from the till - the voucher is the evidence."""
        exp.with_user(self.ops_head).action_approve()
        exp.with_user(self.finance).action_submit_settlement()
        exp.with_user(self.finance_head).action_approve_settlement()
        action = exp.with_user(self.cashier).action_open_settle_wizard()
        wizard = self.env['logistics.expense.settle.wizard'].with_user(
            self.cashier).with_context(action['context']).create({})
        wizard.action_pay()
        self.assertEqual(exp.state, 'settled')
        return wizard

    # =================================================================
    # 1. who collects the cash: the requester, unless they say otherwise
    # =================================================================
    def test_01_the_dialog_names_the_requester_as_collector(self):
        file = self._working_file()
        Wizard = self.env['logistics.expense.capture.wizard'].with_user(
            self.ops_agent).with_context(active_id=file.id)
        defaults = Wizard.default_get(['collector_id', 'employee_id'])
        self.assertEqual(defaults.get('collector_id'), self.requester_emp.id,
                         "the requester collects the cash by default")
        exp = self._capture(file, vendor_id=self.vendor.id)
        self.assertEqual(exp.collector_id, self.requester_emp)
        self.assertEqual(exp.payment_mode, 'cash')
        self.assertFalse(exp.employee_id, "a supplier payment has no holder")
        self.assertEqual(exp.vendor_id, self.vendor)

    def test_02_the_requester_may_name_somebody_else_until_approved(self):
        file = self._working_file()
        exp = self._capture(file, vendor_id=self.vendor.id,
                            collector_id=self.courier_emp.id)
        self.assertEqual(exp.collector_id, self.courier_emp)
        # theirs while submitted
        exp.with_user(self.ops_agent).write(
            {'collector_id': self.requester_emp.id})
        self.assertEqual(exp.collector_id, self.requester_emp)
        self.assertTrue(exp.with_user(self.ops_agent).can_edit_collector)
        # approved: Finance's now
        exp.with_user(self.ops_head).action_approve()
        self.assertFalse(exp.with_user(self.ops_agent).can_edit_collector)
        with self.assertRaises(UserError):
            exp.with_user(self.ops_agent).write(
                {'collector_id': self.courier_emp.id})
        self.assertTrue(exp.with_user(self.finance).can_edit_collector)
        exp.with_user(self.finance).write({'collector_id': self.courier_emp.id})
        self.assertEqual(exp.collector_id, self.courier_emp)
        # paid out: nobody's - the voucher names the collector for good
        exp.with_user(self.finance).action_submit_settlement()
        exp.with_user(self.finance_head).action_approve_settlement()
        action = exp.with_user(self.cashier).action_open_settle_wizard()
        wizard = self.env['logistics.expense.settle.wizard'].with_user(
            self.cashier).with_context(action['context']).create({})
        self.assertEqual(wizard.collector_id, self.courier_emp,
                         "the cashier is told whom to hand the cash to")
        wizard.action_pay()
        self.assertFalse(exp.with_user(self.finance).can_edit_collector)
        with self.assertRaises(UserError):
            exp.with_user(self.finance).write(
                {'collector_id': self.requester_emp.id})
        # the same (unchanged) value sent back by a form save is not a change
        exp.with_user(self.finance).write({'collector_id': self.courier_emp.id})

    # =================================================================
    # 2. the advance stands against the requester, whoever collected it
    # =================================================================
    def test_03_an_advance_stands_against_the_requester(self):
        file = self._working_file()
        exp = self._capture(file, is_advance=True,
                            collector_id=self.courier_emp.id)
        self.assertEqual(exp.payment_mode, 'advance')
        self.assertEqual(exp.employee_id, self.requester_emp,
                         "the holder is the requester, not chosen")
        self.assertEqual(exp.collector_id, self.courier_emp)
        self.assertFalse(exp.vendor_id)
        self._paid(exp)
        # the entry: 421101 carries the REQUESTER's auxiliary
        line = exp.settlement_move_id.line_ids.filtered(
            lambda l: l.account_id == self.advances)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.partner_id,
                         self.requester_emp._clearance_auxiliary_partner())
        self.assertNotEqual(line.partner_id,
                            self.courier_emp._clearance_auxiliary_partner())
        self.assertEqual(line.debit, 25000)
        # the debt is the requester's to clear, not the courier's
        Task = self.env['clearance.task']
        domain = [('kind', '=', 'advance_justify'),
                  ('res_model', '=', 'logistics.expense'),
                  ('res_id', '=', exp.id)]
        self.assertTrue(Task.with_user(self.ops_agent).search(domain))
        self.assertFalse(Task.with_user(self.courier).search(domain))
        # the voucher tells the cashier whom the cash is handed to
        html = self.env['ir.actions.report']._render_qweb_html(
            'elite_clearance.action_report_cash_voucher', exp.ids)[0]
        if isinstance(html, bytes):
            html = html.decode()
        self.assertIn("REMIS À", html)
        self.assertIn("Courier C", html)
        self.assertIn("Remis à", html)
        self.assertIn("Ops Agent C", html, "the requester prints as DEMANDEUR")

    def test_04_no_employee_record_no_advance(self):
        """An advance has to stand against somebody: a requester with no
        employee record is told so at the dialog, not at the ledger."""
        file = self._working_file()
        self.assertFalse(self.cs_agent.employee_id)
        wizard = self.env['logistics.expense.capture.wizard'].with_user(
            self.cs_agent).with_context(active_id=file.id).create({
                'category_id': self.category.id, 'description': "Avance",
                'amount': 10000, 'journal_id': self.till.id,
                'is_advance': True})
        self.assertFalse(wizard.collector_id,
                         "nobody is offered when the requester has no record")
        with self.assertRaises(UserError):
            wizard.action_submit_close()
        self.assertFalse(file.expense_ids)

    def test_05_finance_turning_a_payment_into_an_advance_gets_the_requester(self):
        file = self._working_file()
        exp = self._capture(file, vendor_id=self.vendor.id)
        exp.with_user(self.ops_head).action_approve()
        exp.with_user(self.finance).write(
            {'payment_mode': 'advance', 'vendor_id': False})
        self.assertEqual(exp.employee_id, self.requester_emp,
                         "the holder is the requester, filled in by itself")
        self.assertEqual(exp.collector_id, self.requester_emp)

    def test_06_the_screens_show_the_collector(self):
        Expense = self.env['logistics.expense']
        wizard_arch = self.env['logistics.expense.capture.wizard'].with_user(
            self.ops_agent).get_view(self.env.ref(
                'elite_clearance.expense_capture_wizard_view_form').id)['arch']
        self.assertIn('name="collector_id"', wizard_arch)
        self.assertIn('name="is_advance"', wizard_arch)
        capture = Expense.with_user(self.ops_agent).get_view(self.env.ref(
            'elite_clearance.logistics_expense_view_capture_form').id)['arch']
        self.assertIn('name="collector_id"', capture)
        self.assertRegex(capture, r'<field name="employee_id"[^>]*readonly="1"',
                         "the holder is shown, not chosen")
        form = Expense.with_user(self.finance).get_view(self.env.ref(
            'elite_clearance.logistics_expense_view_form').id)['arch']
        self.assertIn('name="collector_id"', form)
        settle = self.env['logistics.expense.settle.wizard'].with_user(
            self.cashier).get_view(self.env.ref(
                'elite_clearance.expense_settle_wizard_view_form').id)['arch']
        self.assertIn('Hand the Cash To', settle)

    # =================================================================
    # 3. the transit order after work has started
    # =================================================================
    def test_07_customer_service_changes_the_transit_order_after_work_starts(self):
        file = self._file(user=self.cs_agent,
                          transit_authorisation_ref="OT-2026-0001")
        file = file.with_env(self.env)
        file.state = 'in_progress'
        file.with_user(self.cs_agent).write(
            {'transit_authorisation_ref': "OT-2026-0002"})
        self.assertEqual(file.transit_authorisation_ref, "OT-2026-0002")
        # through the form, as the browser would: the field is editable
        with Form(file.with_user(self.cs_agent)) as form:
            form.transit_authorisation_ref = "OT-2026-0003"
        self.assertEqual(file.transit_authorisation_ref, "OT-2026-0003")
        arch = self.env['logistics.file'].with_user(self.cs_agent).get_view(
            self.env.ref('elite_clearance.logistics_file_view_form').id)['arch']
        self.assertRegex(arch, r'<field name="transit_authorisation_ref"[^>]*>')
        self.assertNotRegex(
            arch, r'<field name="transit_authorisation_ref"[^>]*readonly',
            "nothing locks the transit order once work has started")
