"""Owner spec 15/09/2026, four instructions.

Frais de dossier as a third revenue line; client advances recorded as
real receipts against the client's account and shown on the invoice;
undisclosed client accounts numbered from their own series; and expense
categories that can never be justified, so an advance for one of them
holds nothing up.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec1509(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'V4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.advance_account = Account.create({
            'code': 'V421101', 'name': "Personnel debours avances",
            'account_type': 'asset_current', 'reconcile': True})
        cls.commission = Account.create({
            'code': 'V70621', 'name': "Commission", 'account_type': 'income'})
        cls.service_fee = Account.create({
            'code': 'V70622', 'name': "HAD", 'account_type': 'income'})
        cls.file_fee = Account.create({
            'code': 'V70623', 'name': "Frais de dossier",
            'account_type': 'income'})
        cls.under = Account.create({
            'code': 'V65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'V75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales 1509", 'type': 'sale', 'code': 'VSAL9'})
        cls.misc = env['account.journal'].create({
            'name': "Misc 1509", 'type': 'general', 'code': 'VMIS9'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advance_account.id,
            'clearance_fee_account_id': cls.commission.id,
            'clearance_commission_account_id': cls.commission.id,
            'clearance_service_fee_account_id': cls.service_fee.id,
            'clearance_file_fee_account_id': cls.file_fee.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_misc_journal_id': cls.misc.id,
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash 1509", 'type': 'cash', 'code': 'VCSH9'})
        cls.bank = env['account.journal'].create({
            'name': "Bank 1509", 'type': 'bank', 'code': 'VBNK9'})

        def client(name, disclosure='disclosed'):
            return env['res.partner'].create({
                'name': name, 'is_company': True,
                'street': "BP 15 Douala", 'email': "c1509@test.cm",
                'vat': "M000000000041A",
                'company_registry': "RC/DLA/2026/B/0041",
                'clearance_invoice_name': name.upper() + " SARL",
                'clearance_disclosure': disclosure})
        cls.client = client("Spec Client")
        cls.hidden_client = client("Hidden Client", 'undisclosed')
        cls.vendor = env['res.partner'].create({
            'name': "Terminal 1509", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port 1509", 'code': "V-PRT"})
        cls.unjustifiable = env['logistics.expense.category'].create({
            'name': "Frais extra-legaux 1509", 'code': "V-XLEG",
            'justification': 'non_justifiable'})
        cls.service = env['logistics.service.type'].create({
            'name': "Spec 1509", 'code': "V-SPC", 'commission_rate': 2.0})
        cls.employee = env['hr.employee'].create({'name': "Agent 1509"})

    def _file(self, partner=None):
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW001509",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': (partner or self.client).id,
            'service_type_id': self.service.id})
        file.state = 'in_progress'
        file.customs_fee_amount = 30000
        return file

    def _disburse(self, file, amount=100000, category=None, advance=False):
        expense = self.env['logistics.expense'].create({
            'file_id': file.id, 'category_id': (category or self.category).id,
            'description': "Handling", 'amount': amount})
        expense.action_submit()
        expense.action_approve()
        if advance:
            expense.write({'payment_mode': 'advance',
                           'journal_id': self.cash.id,
                           'employee_id': self.employee.id})
        else:
            expense.write({'payment_mode': 'cash',
                           'journal_id': self.cash.id,
                           'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        return expense

    def _wizard(self, file):
        return self.env['logistics.billing.wizard'].with_context(
            active_id=file.id).create({})

    # =================================================================
    # 1. Frais de dossier
    # =================================================================
    def test_01_frais_de_dossier_is_billed_to_its_own_account(self):
        file = self._file()
        self._disburse(file)
        file.action_close_operations()
        wizard = self._wizard(file)
        self.assertEqual(wizard.file_fee_amount, 0, "nothing until it is keyed")
        wizard.file_fee_amount = 15000
        self.assertEqual(wizard.service_total, 2000 + 30000 + 15000)
        wizard.action_create_invoice()

        line = file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.clearance_service_kind == 'file_fee')
        self.assertEqual(len(line), 1)
        self.assertEqual(line.price_subtotal, 15000)
        self.assertEqual(line.account_id, self.file_fee,
                         "its own revenue account, not the commission's")
        self.assertEqual(line.name, "Frais de dossier")
        self.assertEqual(file.file_fee_amount, 15000, "recorded on the file")

    def test_02_it_is_not_charged_twice_on_a_second_bill(self):
        file = self._file()
        self._disburse(file)
        file.action_close_operations()
        wizard = self._wizard(file)
        wizard.file_fee_amount = 15000
        wizard.action_create_invoice()
        file.invoice_id.action_post()

        self.env['logistics.file.reopen.wizard'].create({
            'file_id': file.id, 'target_state': 'in_progress',
            'reason': "A late cost."}).action_reopen()
        self._disburse(file, 20000)
        file.action_close_operations()

        again = self._wizard(file)
        self.assertEqual(again.file_fee_billed, 15000)
        self.assertEqual(again.file_fee_amount, 0,
                         "already charged, so not proposed again")

    # =================================================================
    # 2. A client advance, recorded and shown
    # =================================================================
    def test_03_a_client_advance_is_a_receipt_on_the_clients_account(self):
        file = self._file()
        wizard = self.env['logistics.client.advance.wizard'].with_context(
            active_id=file.id).create({
                'amount': 250000, 'journal_id': self.bank.id,
                'memo': "TRF-0099"})
        wizard.action_record_advance()

        payment = file.client_advance_ids
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.partner_id, self.client)
        self.assertEqual(payment.amount, 250000)
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(payment.logistics_file_id, file,
                         "the receipt belongs to the file")
        self.assertEqual(file.client_advance_total, 250000)
        # every line of it carries the file, like everything else it touches
        analytic = str(file.analytic_account_id.id)
        for line in payment.move_id.line_ids:
            self.assertIn(analytic, line.analytic_distribution or {})

    def test_04_the_advance_comes_off_the_invoice(self):
        file = self._file()
        self._disburse(file)
        self.env['logistics.client.advance.wizard'].with_context(
            active_id=file.id).create({
                'amount': 50000, 'journal_id': self.bank.id
            }).action_record_advance()
        file.action_close_operations()
        self._wizard(file).action_create_invoice()
        invoice = file.invoice_id

        advances = invoice._clearance_advances()
        self.assertEqual(len(advances), 4)
        self.assertEqual(advances[3], 50000, "the receipts are the fourth row")
        self.assertEqual(invoice._clearance_advance_total(), 50000)
        self.assertEqual(file.invoice_balance_due,
                         invoice.amount_total - 50000)
        html = self.env['ir.actions.report']._render_qweb_html(
            'elite_clearance.report_clearance_invoice', invoice.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("AVANCES ENCAISS", html)
        self.assertIn(invoice._clearance_money(50000), html)

    def test_05_an_invoice_with_no_advance_reads_as_it_always_did(self):
        file = self._file()
        self._disburse(file)
        file.action_close_operations()
        self._wizard(file).action_create_invoice()
        html = self.env['ir.actions.report']._render_qweb_html(
            'elite_clearance.report_clearance_invoice',
            file.invoice_id.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertNotIn("AVANCES ENCAISS", html)

    # =================================================================
    # 3. Undisclosed accounts take their own numbering
    # =================================================================
    def test_06_an_undisclosed_client_is_numbered_from_its_own_series(self):
        company = self.env.company
        self.assertTrue(company.clearance_undisclosed_file_sequence_id,
                        "seeded at install and named on the company")
        plain = self._file()
        self.assertTrue(plain.name.startswith("2026V-SPC")
                        or "V-SPC" in plain.name, plain.name)

        hidden = self._file(self.hidden_client)
        self.assertTrue(hidden.name.startswith("UD"), hidden.name)
        self.assertNotIn("V-SPC", hidden.name,
                         "the service type is not on it either")
        self.assertEqual(hidden.partner_disclosure, 'undisclosed')

        self._disburse(hidden)
        hidden.action_close_operations()
        self._wizard(hidden).action_create_invoice()
        self.assertTrue(hidden.invoice_id.name.startswith("UD"),
                        hidden.invoice_id.name)

    def test_07_an_undisclosed_client_without_a_series_is_refused_clearly(self):
        company = self.env.company
        company.clearance_undisclosed_file_sequence_id = False
        with self.assertRaises(UserError) as caught:
            self._file(self.hidden_client)
        self.assertIn("undisclosed", str(caught.exception).lower())

    # =================================================================
    # 4. What can never be justified is not waited on
    # =================================================================
    def test_08_a_non_justifiable_advance_never_reaches_421101(self):
        file = self._file()
        expense = self._disburse(file, 40000, category=self.unjustifiable,
                                 advance=True)
        self.assertFalse(expense.justification_required)
        self.assertEqual(expense.state, 'settled')
        move = expense.settlement_move_id
        debits = move.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(debits.account_id, self.engaged,
                         "spent the moment it was handed over")
        self.assertNotIn(self.advance_account, move.line_ids.account_id)

    def test_09_it_holds_nothing_up_and_is_billable_at_once(self):
        file = self._file()
        expense = self._disburse(file, 40000, category=self.unjustifiable,
                                 advance=True)
        self.assertEqual(file.unjustified_advance_total, 0,
                         "there is no document to wait for")
        self.assertIn(expense, file._billable_expenses())
        self.assertEqual(file.oop_total, 40000)
        # and the file closes and bills without a waiver
        file.action_close_operations()
        self.assertEqual(file.state, 'ops_closed')
        self._wizard(file).action_create_invoice()
        self.assertTrue(file.invoice_id)

    def test_10_a_justifiable_advance_still_holds_the_file(self):
        file = self._file()
        expense = self._disburse(file, 40000, advance=True)
        self.assertTrue(expense.justification_required)
        self.assertEqual(file.unjustified_advance_total, 40000)
        self.assertNotIn(expense, file._billable_expenses())
        with self.assertRaises(UserError):
            file.action_close_operations()

    def test_11_there_is_nothing_to_submit_for_a_non_justifiable_cost(self):
        file = self._file()
        expense = self._disburse(file, 40000, category=self.unjustifiable,
                                 advance=True)
        self.env['ir.attachment'].create({
            'name': "receipt.pdf", 'res_model': 'logistics.expense',
            'res_id': expense.id, 'raw': b"x"})
        with self.assertRaises(UserError) as caught:
            expense.action_submit_justification()
        self.assertIn("no document to produce", str(caught.exception))

    def test_12_the_holders_queue_leaves_it_alone(self):
        file = self._file()
        expense = self._disburse(file, 40000, category=self.unjustifiable,
                                 advance=True)
        user = self.env['res.users'].create({
            'name': "Holder 1509", 'login': "holder.1509@clearance.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_operations').id])]})
        self.employee.user_id = user.id
        queue = self.env['clearance.task'].with_user(user).search([
            ('kind', '=', 'advance_justify')])
        self.assertNotIn(expense.id, queue.mapped('res_id'),
                         "nobody is asked for a document that cannot exist")
