"""Owner spec 10/10/2026.

File numbering that carries on from the old system, VAT that follows the
settings and the customer, refusals that say why, a recharge reviewed on
the billing screen with a reason on every line, and a bell that lists
the newest task first.
"""

import json

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec1010(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'Y4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.advances = Account.create({
            'code': 'Y421101', 'name': "Personnel debours avances",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'Y70621', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'Y65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'Y75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.vat = env['account.tax'].create({
            'name': "TVA 19,25% Y", 'amount': 19.25,
            'amount_type': 'percent', 'type_tax_use': 'sale'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales 1010", 'type': 'sale', 'code': 'YSAL'})
        cls.cash = env['account.journal'].create({
            'name': "Caisse 1010", 'type': 'cash', 'code': 'YCSH'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advances.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_commission_account_id': cls.fee.id,
            'clearance_service_fee_account_id': cls.fee.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_service_tax_ids': [(6, 0, cls.vat.ids)],
        })
        cls.client = env['res.partner'].create({
            'name': "Spec Client 1010", 'is_company': True,
            'street': "BP 10 Douala", 'email': "c1010@test.cm",
            'vat': "M000000000101A",
            'company_registry': "RC/DLA/2026/B/0101",
            'clearance_invoice_name': "SPEC CLIENT 1010 SARL"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal 1010", 'is_company': True, 'supplier_rank': 1})
        cls.employee = env['hr.employee'].create({'name': "Agent 1010"})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port 1010", 'code': "T-P10"})
        cls.service = env['logistics.service.type'].create({
            'name': "Spec 1010", 'code': "T-S10", 'commission_rate': 2.0})

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@1010.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.agent = user("Ops Agent 1010", 'operations')
        cls.ops_head = user("Ops Head 1010", 'ops_manager')
        cls.gm = user("GM 1010", 'manager')
        cls.billing = user("Billing 1010", 'billing')
        cls.admin = user("Clearance Admin 1010", 'admin')

    # ------------------------------------------------------------------
    def _file(self, service=None):
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW001010",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': self.client.id,
            'service_type_id': (service or self.service).id})
        file.state = 'in_progress'
        file.customs_fee_amount = 30000
        return file

    def _paid(self, file, amount, user=None):
        Expense = self.env['logistics.expense']
        if user:
            Expense = Expense.with_user(user)
        exp = Expense.create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Manutention", 'amount': amount,
            'vendor_id': self.vendor.id, 'journal_id': self.cash.id})
        exp = exp.sudo()
        exp.action_submit()
        exp.action_approve()
        exp.action_submit_settlement()
        exp.action_approve_settlement()
        exp.action_settle()
        return exp

    def _wizard(self, file, user=None, review=False):
        Wizard = self.env['logistics.billing.wizard']
        if user:
            Wizard = Wizard.with_user(user)
        ctx = {'active_id': file.id}
        if review:
            ctx['clearance_billing_review'] = True
        return Wizard.with_context(**ctx).create({})

    def _bus(self):
        queued = self.env.cr.precommit.data.get("bus.bus.values", [])
        return [json.loads(row["message"]) for row in queued
                if json.loads(row["message"])["type"] == 'elite_clearance.task']

    # ==================================================================
    # 1. file creation
    # ==================================================================
    def test_01_the_follow_up_employee_is_off_the_form(self):
        arch = etree.fromstring(
            self.env['logistics.file'].get_view(view_type='form')['arch'])
        self.assertFalse(arch.xpath("//group[@name='cargo']//field[@name='employee_id']"))
        self.assertTrue(arch.xpath("//field[@name='user_id']"),
                        "the Responsible user is the one who follows a file")

    def test_02_numbering_continues_from_the_legacy_system(self):
        service = self.env['logistics.service.type'].create({
            'name': "Legacy numbered", 'code': "ZZ",
            'legacy_last_file_ref': "2026zz0019"})
        self.assertEqual(service.legacy_last_file_ref, "2026ZZ0019")
        file = self._file(service)
        self.assertEqual(file.name, "2026ZZ0020")
        self.assertEqual(self._file(service).name, "2026ZZ0021")
        with self.assertRaisesRegex(UserError, "already been opened"):
            service.legacy_last_file_ref = "2026ZZ0005"
        with self.assertRaisesRegex(UserError, "not a Legacy numbered file number"):
            service.legacy_last_file_ref = "IM-19"
        # moving it forward is allowed
        service.legacy_last_file_ref = "2026ZZ0100"
        self.assertEqual(self._file(service).name, "2026ZZ0101")

    # ==================================================================
    # 2. VAT and the printed commission line
    # ==================================================================
    def _invoice(self, file):
        file.action_close_operations()
        file.action_create_invoice()
        return file.invoice_id

    def test_03_vat_comes_from_clearance_settings_first(self):
        invoice = self._invoice(self._file())
        services = invoice.invoice_line_ids.filtered(
            lambda l: l.clearance_category == 'prestation')
        self.assertEqual(services.tax_ids, self.vat)
        self.assertAlmostEqual(invoice.amount_tax, 30000 * 0.1925, places=2)

    def test_04_then_from_the_accounting_default_sales_tax(self):
        company = self.env.company
        company.clearance_service_tax_ids = [(5, 0, 0)]
        default = self.env['account.tax'].create({
            'name': "Default 10 Y", 'amount': 10.0,
            'amount_type': 'percent', 'type_tax_use': 'sale'})
        company.account_sale_tax_id = default
        invoice = self._invoice(self._file())
        self.assertAlmostEqual(invoice.amount_tax, 3000, places=2)

    def test_05_an_exempt_customer_pays_no_vat_and_nothing_configured_is_refused(self):
        self.client.clearance_vat_exempt = True
        invoice = self._invoice(self._file())
        self.assertEqual(invoice.amount_tax, 0)
        self.assertFalse(invoice.invoice_line_ids.mapped('tax_ids'))
        self.client.clearance_vat_exempt = False
        company = self.env.company
        company.clearance_service_tax_ids = [(5, 0, 0)]
        company.account_sale_tax_id = False
        file = self._file()
        file.action_close_operations()
        with self.assertRaisesRegex(UserError, "No VAT is configured"):
            file.action_create_invoice()

    def test_06_the_commission_line_carries_no_percentage(self):
        file = self._file()
        self._paid(file, 100000)
        invoice = self._invoice(file)
        commission = invoice.invoice_line_ids.filtered(
            lambda l: l.clearance_service_kind == 'commission')
        self.assertEqual(commission.name, "Commission sur débours")
        self.assertEqual(commission.price_subtotal, 2000)
        self.assertNotIn("%", commission.name)

    # ==================================================================
    # 3. roles and refusals
    # ==================================================================
    def test_07_the_administrator_passes_a_named_approver_list(self):
        self.env.company.clearance_expense_approver_ids = [(6, 0, self.ops_head.ids)]
        file = self._file()
        exp = self.env['logistics.expense'].create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Manutention", 'amount': 5000,
            'vendor_id': self.vendor.id, 'journal_id': self.cash.id})
        exp.action_submit()
        with self.assertRaises(UserError):
            exp.with_user(self.gm).action_approve()
        exp.with_user(self.admin).action_approve()
        self.assertEqual(exp.state, 'approved')

    def test_08_a_refusal_carries_its_reason_to_the_requester(self):
        file = self._file()
        exp = self.env['logistics.expense'].with_user(self.agent).create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Manutention", 'amount': 5000,
            'vendor_id': self.vendor.id, 'journal_id': self.cash.id})
        exp.with_user(self.agent).action_submit()
        # the button opens the dialog ...
        action = exp.with_user(self.ops_head).with_context(
            rejection_method='action_refuse').action_open_rejection()
        self.assertEqual(action['res_model'], 'clearance.rejection.wizard')
        Dialog = self.env['clearance.rejection.wizard'].with_user(self.ops_head)
        # only a refusal can be called through it
        with self.assertRaises(UserError):
            Dialog.create({
                'res_model': 'logistics.expense', 'res_ids': str(exp.id),
                'method': 'action_settle', 'reason': "x"}).action_confirm()
        # ... and the dialog refuses with the reason
        Dialog.with_context(**action['context']).create(
            {'reason': "Already paid on EXP/0041."}).action_confirm()
        self.assertEqual(exp.state, 'cancel')
        message = exp.message_ids.sorted('id')[-1]
        self.assertIn("Already paid on EXP/0041.", message.body)
        self.assertIn(self.agent.partner_id, message.partner_ids,
                      "the person who keyed it is told why")

    def test_09_the_opening_refusal_takes_the_dialogs_reason_as_its_note(self):
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4', 'bl_awb_ref': "MEDUW001011",
            'goods_description': "Marchandises", 'cargo_value': 10.0,
            'partner_id': self.client.id,
            'service_type_id': self.service.id})
        file.opening_state = 'requested'
        file.with_context(
            clearance_rejection_reason="Wrong client.").action_refuse_opening()
        self.assertEqual(file.opening_state, 'refused')
        self.assertEqual(file.opening_note, "Wrong client.")

    # ==================================================================
    # 4. the recharge: a reason on every line, reviewed on the screen
    # ==================================================================
    def test_10_each_line_that_differs_says_why(self):
        file = self._file()
        self._paid(file, 100000)
        self._paid(file, 50000)
        file.action_close_operations()
        wizard = self._wizard(file)
        first = wizard.debours_line_ids[0]
        first.amount_recharged = 90000
        with self.assertRaisesRegex(UserError, "Why column"):
            wizard.action_submit_for_review()
        first.comment = "Client disputes 10 000 of the handling"
        wizard.action_submit_for_review()
        self.assertEqual(file.recharge_state, 'requested')
        self.assertEqual(first.expense_id.recharge_comment,
                         "Client disputes 10 000 of the handling")
        self.assertIn("Client disputes 10 000", file.recharge_reason,
                      "the line comments are the file's reason")
        # a line at cost needs no comment
        self.assertFalse(wizard.debours_line_ids[1].comment)
        return file

    def test_11_the_approver_reviews_on_the_billing_screen(self):
        file = self.test_10_each_line_that_differs_says_why()
        # the queue sends the Ops head straight to the screen
        task = self.env['clearance.task'].with_user(self.ops_head).search(
            [('kind', '=', 'recharge_ops'), ('file_id', '=', file.id)])
        self.assertEqual(len(task), 1)
        action = task.action_open()
        self.assertEqual(action['res_model'], 'logistics.billing.wizard')
        self.assertTrue(action['context']['clearance_billing_review'])
        # the screen opens for a head with no accounting rights ...
        review = self._wizard(file, user=self.ops_head, review=True)
        self.assertTrue(review.review_mode)
        line = review.debours_line_ids.filtered(lambda l: l.variance)
        self.assertEqual(line.amount_recharged, 90000)
        self.assertEqual(line.comment, "Client disputes 10 000 of the handling")
        self.assertTrue(review.needs_review)
        # ... and signs from it; below cost, the GM signs next
        review.action_approve_review()
        self.assertEqual(file.recharge_state, 'ops_approved')
        with self.assertRaises(UserError):
            self._wizard(file, user=self.ops_head, review=True).action_approve_review()
        self._wizard(file, user=self.gm, review=True).action_approve_review()
        self.assertEqual(file.recharge_state, 'approved')
        # the biller's screen is then free to invoice
        self.assertFalse(self._wizard(file).needs_review)

    def test_12_the_screens_refusal_asks_for_a_reason(self):
        file = self.test_10_each_line_that_differs_says_why()
        review = self._wizard(file, user=self.ops_head, review=True)
        action = review.action_refuse_review()
        self.assertEqual(action['res_model'], 'clearance.rejection.wizard')
        self.env['clearance.rejection.wizard'].with_user(
            self.ops_head).with_context(**action['context']).create(
                {'reason': "Charge the full cost."}).action_confirm()
        self.assertEqual(file.recharge_state, 'refused')
        self.assertIn("Charge the full cost.",
                      file.message_ids.sorted('id')[-1].body)

    # ==================================================================
    # 5. the bell
    # ==================================================================
    def test_13_a_proposed_service_rings_and_the_newest_task_is_first(self):
        before = len(self._bus())
        self.env['logistics.billing.service'].create({
            'name': "Escorte 1010", 'default_amount': 25000})
        rung = [m for m in self._bus()[before:]
                if m['payload']['kind'] == 'billing_service']
        self.assertTrue(rung, "Operations is told a service awaits approval")
        file = self._file()
        tasks = self.env['clearance.task'].search(
            [], order='date_landed desc, id desc', limit=5)
        self.assertTrue(tasks)
        self.assertEqual(tasks[0].file_id, file,
                         "the file just opened is the newest row")
        dates = tasks.mapped('date_landed')
        self.assertEqual(dates, sorted(dates, reverse=True))
