"""Owner spec 10/10/2026, second message: every team sees every file,
the files one is working on sit in My Tasks, one list of payment
channels for everybody, the ledger reads "<category> / <file>", the
petty-cash voucher, and a recharge reviewed line by line."""

import base64

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .holding import give_holding_account


@tagged('post_install', '-at_install')
class TestOwnerSpec1010b(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'B4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'B70621', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'B65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'B75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales 1010b", 'type': 'sale', 'code': 'BSALS'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_commission_account_id': cls.fee.id,
            'clearance_service_fee_account_id': cls.fee.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'street': "BP 5077 DLA BONAPRISO",
            'company_registry': "RC/DLA/2018/B/2056",
            'phone': "233 43 48 82",
        })
        cls.till = env['account.journal'].create({
            'name': "Caisse principale", 'type': 'cash', 'code': 'BCSH'})
        cls.bank = env['account.journal'].create({
            'name': "AFB", 'type': 'bank', 'code': 'BAFB'})
        give_holding_account(cls.bank)
        cls.client = env['res.partner'].create({
            'name': "Softcare", 'is_company': True,
            'street': "BP 12 Douala", 'email': "softcare@test.cm",
            'vat': "M000000000061B",
            'company_registry': "RC/DLA/2026/B/0061",
            'clearance_invoice_name': "SOFTCARE CAMEROON LIMITED",
            'clearance_vat_exempt': True})
        cls.vendor = env['res.partner'].create({
            'name': "Kribi Conteneurs Terminal", 'is_company': True,
            'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Retour vide", 'code': "B-RTV"})
        cls.service = env['logistics.service.type'].create({
            'name': "Spec 1010b", 'code': "B-SPC", 'commission_rate': 2.0})

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@1010b.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.cs_agent = user("Blanche Kounche", 'customer_service')
        cls.cs_head = user("CS Head B", 'customer_service_manager')
        cls.ops_agent = user("Ops Agent B", 'operations')
        cls.ops_head = user("Ravie Fokam", 'ops_manager')
        cls.transit = user("Transit Agent B", 'transit')
        cls.finance = user("Cherifa Njoupouo", 'finance')
        cls.finance_head = user("Finance Head B", 'finance_manager')
        cls.cashier = user("Cashier B", 'cashier')
        cls.gm = user("General Manager B", 'manager')
        cls.biller = user("Biller B", 'billing')

    # -----------------------------------------------------------------
    def _file(self, user=None, **extra):
        File = self.env['logistics.file']
        if user:
            File = File.with_user(user)
        vals = {
            'customs_regime': 'im4', 'bl_awb_ref': "MEDUB000577",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0, 'partner_id': self.client.id,
            'service_type_id': self.service.id}
        vals.update(extra)
        return File.create(vals)

    def _working_file(self):
        file = self._file()
        file.state = 'in_progress'
        return file

    def _expense(self, file, amount=53081, journal=None, requester=None):
        """Keyed by Operations, approved by its head, prepared by Finance,
        signed by the Head of Service Finance: ready to pay."""
        journal = journal or self.till
        requester = requester or self.ops_agent
        exp = self.env['logistics.expense'].with_user(requester).create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Retour conteneur vide", 'amount': amount,
            'journal_id': journal.id, 'vendor_id': self.vendor.id})
        exp.action_submit()
        # back in the root env: each step below says who performs it
        exp = exp.with_env(self.env)
        exp.with_user(self.ops_head).action_approve()
        exp.with_user(self.finance).action_submit_settlement()
        exp.with_user(self.finance_head).action_approve_settlement()
        return exp

    def _document(self, name, res_model, res_id, user=None):
        Attachment = self.env['ir.attachment']
        if user:
            Attachment = Attachment.with_user(user)
        return Attachment.create({
            'name': name, 'res_model': res_model, 'res_id': res_id,
            'datas': base64.b64encode(b"%PDF-1.4 1010b")})

    def _settled(self, file, amount, journal=None):
        exp = self._expense(file, amount, journal=journal)
        exp.action_settle()
        return exp

    def _wizard(self, file, user=None):
        Wizard = self.env['logistics.billing.wizard']
        if user:
            Wizard = Wizard.with_user(user)
        return Wizard.with_context(active_id=file.id).create({})

    # =================================================================
    # 1. every clearance team sees a file from the moment it is opened
    def test_01_every_team_sees_a_file_customer_service_has_opened(self):
        file = self._file(user=self.cs_agent)
        self.assertEqual(file.state, 'draft')
        for who in (self.cs_agent, self.cs_head, self.ops_agent, self.ops_head,
                    self.transit, self.finance):
            found = self.env['logistics.file'].with_user(who).search(
                [('id', '=', file.id)])
            self.assertEqual(found, file, "%s sees it under Files" % who.name)
            self.assertTrue(file.with_user(who).read(['name']))
            # and its checklist with it
            self.assertEqual(
                self.env['logistics.file.document'].with_user(who).search(
                    [('file_id', '=', file.id)]),
                file.document_ids)

    # 2. a cost keyed on a file puts it in the requester's Ongoing files
    def test_02_a_cost_keyed_on_a_file_makes_it_an_ongoing_file(self):
        file = self._working_file()
        Task = self.env['clearance.task']

        def ongoing(user):
            return Task.with_user(user).search(
                [('kind', '=', 'ongoing_file'), ('file_id', '=', file.id)])
        self.assertFalse(ongoing(self.ops_agent), "nothing keyed yet")
        exp = self.env['logistics.expense'].with_user(self.ops_agent).create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Retour conteneur vide", 'amount': 53081})
        rows = ongoing(self.ops_agent)
        self.assertEqual(len(rows), 1, "the file, once, for the requester")
        self.assertEqual(rows.res_model, 'logistics.file')
        self.assertEqual(rows.res_id, file.id)
        self.assertEqual(rows.holder_user_id, self.ops_agent)
        self.assertEqual(rows.kind_label, "Ongoing files")
        self.assertFalse(ongoing(self.transit),
                         "somebody who keyed nothing on it does not see it")
        # a second cost by the same person is still ONE row
        self.env['logistics.expense'].with_user(self.ops_agent).create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Manutention", 'amount': 10000})
        self.assertEqual(len(ongoing(self.ops_agent)), 1)
        exp.action_submit()
        self.assertTrue(ongoing(self.ops_agent), "still ongoing once submitted")
        # closed for operations: no longer ongoing
        file.state = 'ops_closed'
        self.assertFalse(ongoing(self.ops_agent))
        # the queue opens the file itself
        file.state = 'in_progress'
        action = ongoing(self.ops_agent).action_open()
        self.assertEqual(action['res_model'], 'logistics.file')
        self.assertEqual(action.get('res_id'), file.id)

    # 3. one fixed list of payment channels for everybody
    def test_03_the_payment_channel_is_one_fixed_list_of_tills_and_banks(self):
        Expense = self.env['logistics.expense']
        domain = Expense.fields_get(['journal_id'])['journal_id']['domain']
        self.assertIn("'type'", str(domain))
        self.assertIn("'cash'", str(domain))
        self.assertIn("'bank'", str(domain))
        for xmlid in ('elite_clearance.logistics_expense_view_form',
                      'elite_clearance.logistics_expense_view_capture_form'):
            arch = Expense.with_user(self.finance).get_view(
                self.env.ref(xmlid).id)['arch']
            self.assertRegex(
                arch, r'<field name="journal_id"[^>]*widget="selection"',
                "%s lists every channel the same way for everybody" % xmlid)
        arch = self.env['logistics.expense.capture.wizard'].get_view(
            self.env.ref(
                'elite_clearance.expense_capture_wizard_view_form').id)['arch']
        self.assertRegex(arch, r'<field name="journal_id"[^>]*widget="selection"')
        # what the selection widget lists: name_search under that domain
        listed = self.env['account.journal'].with_user(self.finance).name_search(
            "", args=[('type', 'in', ('cash', 'bank'))])
        names = {name for _id, name in listed}
        self.assertIn("Caisse principale", names)
        self.assertIn("AFB", names)
        self.assertNotIn("Sales 1010b", names)

    # 4. the ledger reads "<category> / <file>"
    def test_04_every_journal_item_reads_category_slash_file(self):
        file = self._working_file()
        exp = self._settled(file, 47000, journal=self.bank)
        label = "Retour vide / %s" % file.name
        self.assertEqual(exp._ledger_label(), label)
        move = exp.settlement_move_id
        self.assertTrue(move)
        self.assertEqual(set(move.line_ids.mapped('name')), {label},
                         "the requester's free text is not the ledger label")
        self.assertIn(label, move.ref)
        self.assertIn(exp.name, move.ref, "the entry still names the expense")

    # 5. cash prints its voucher; the file waits for the signed copy
    def test_05_cash_prints_a_voucher_and_the_signed_copy_closes_the_file(self):
        file = self._working_file()
        exp = self._expense(file, 53081, journal=self.till)
        self.assertEqual(exp.approved_by_id, self.ops_head)
        self.assertEqual(exp.settlement_submitted_by_id, self.finance)
        self.assertEqual(exp.settlement_approved_by_id, self.finance_head)

        # the cashier pays from the till with nothing attached
        action = exp.with_user(self.cashier).action_open_settle_wizard()
        wizard = self.env['logistics.expense.settle.wizard'].with_user(
            self.cashier).with_context(action['context']).create({})
        self.assertEqual(wizard.journal_type, 'cash')
        wizard.action_pay()
        self.assertEqual(exp.state, 'settled')
        self.assertEqual(exp.settled_by_id, self.cashier)

        voucher = exp.cash_voucher_ids
        self.assertEqual(len(voucher), 1, "one voucher, printed at payment")
        self.assertEqual(voucher.clearance_kind, 'voucher')
        self.assertTrue(voucher.name.startswith("Avance frais"))
        self.assertTrue(voucher.raw)
        self.assertNotIn(voucher, exp.attachment_ids,
                         "a voucher is not a receipt and never a justification")
        self.assertFalse(exp.payment_evidence_ids)
        self.assertFalse(exp.date_documents_submitted,
                         "the voucher does not date a supporting document")

        # what the document says
        html = self.env['ir.actions.report']._render_qweb_html(
            'elite_clearance.action_report_cash_voucher', exp.ids)[0]
        if isinstance(html, bytes):
            html = html.decode()
        for text in ("AVANCE FRAIS N°", exp.name, "Caisse principale",
                     "Ops Agent B", file.name, "SOFTCARE CAMEROON LIMITED",
                     "Retour vide", "APPROBATIONS", "Ravie Fokam",
                     "Cherifa Njoupouo", "Finance Head B", "Cashier B",
                     "Commissionnaire en Douane", "BP 5077 DLA BONAPRISO",
                     "RCCM : RC/DLA/2018/B/2056", "Tel : 233 43 48 82"):
            self.assertIn(text, html, text)

        # printed again from the button
        report = exp.with_user(self.cashier).action_print_cash_voucher()
        self.assertEqual(report['type'], 'ir.actions.report')
        self.assertEqual(report['report_name'], 'elite_clearance.report_cash_voucher')

        # the file waits for the signed copy
        with self.assertRaises(UserError) as caught:
            file.with_user(self.ops_head).action_close_operations()
        self.assertIn("signed", str(caught.exception))
        signed = self._document("avance-frais-signee.pdf", exp._name, 0,
                                user=self.cashier)
        exp.with_user(self.cashier).write(
            {'signed_voucher_ids': [(4, signed.id)]})
        self.assertEqual(signed.clearance_kind, 'signed')
        self.assertEqual(exp.signed_voucher_ids, signed)
        self.assertNotIn(signed, exp.attachment_ids)
        file.with_user(self.ops_head).action_close_operations()
        self.assertEqual(file.state, 'ops_closed')

    def test_05b_a_bank_payment_still_needs_its_evidence(self):
        file = self._working_file()
        exp = self._expense(file, 47000, journal=self.bank)
        treasury = self.env['res.users'].create({
            'name': "Treasury B", 'login': "treasury.b@1010b.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_treasury').id])]})
        wizard = self.env['logistics.expense.settle.wizard'].with_user(
            treasury).with_context(active_id=exp.id).create({})
        self.assertEqual(wizard.journal_type, 'bank')
        with self.assertRaises(UserError):
            wizard.action_pay()
        self.assertFalse(exp.cash_voucher_ids, "no voucher for a bank")

    # 6. a recharge is reviewed line by line, never on the total
    def test_06_an_overcharge_and_an_undercharge_that_cancel_out_still_need_approval(self):
        file = self._working_file()
        first = self._settled(file, 100000)
        second = self._settled(file, 80000)
        file.action_close_operations()

        wizard = self._wizard(file, user=self.biller)
        line1 = wizard.debours_line_ids.filtered(lambda l: l.expense_id == first)
        line2 = wizard.debours_line_ids.filtered(lambda l: l.expense_id == second)
        self.assertFalse(wizard.needs_review)
        line1.amount_recharged = 120000
        line2.amount_recharged = 60000
        self.assertEqual(wizard.debours_variance, 0.0, "the total is at cost")
        self.assertTrue(wizard.needs_review,
                        "and the lines are not: this is a recharge")
        with self.assertRaises(UserError):
            wizard.action_create_invoice()
        line1.comment = "Agreed uplift"
        line2.comment = "Commercial gesture"
        wizard.action_submit_for_review()
        self.assertEqual(file.recharge_state, 'requested')
        self.assertEqual(file.recharge_amount, 180000)
        self.assertEqual(first.recharge_amount, 120000)
        self.assertEqual(second.recharge_amount, 60000)
        self.assertTrue(file._recharge_lines_differ())
        self.assertTrue(file._recharge_below_cost())
        with self.assertRaises(UserError, msg="no screen, no shortcut"):
            file.action_create_invoice()
        # Operations, then the General Manager because one line is below cost
        file.with_user(self.ops_head).action_approve_recharge_ops()
        self.assertEqual(file.recharge_state, 'ops_approved')
        file.with_user(self.gm).action_approve_recharge_gm()
        self.assertEqual(file.recharge_state, 'approved')
        wizard = self._wizard(file, user=self.biller)
        self.assertFalse(wizard.needs_review, "approved for exactly these lines")
        wizard.action_create_invoice()
        self.assertTrue(file.invoice_id)
        charged = {l.clearance_charged for l in file.invoice_id.invoice_line_ids
                   if l.clearance_category == 'debours'}
        self.assertEqual(charged, {120000.0, 60000.0})

    def test_07_moving_the_lines_after_approval_tears_the_approval_up(self):
        file = self._working_file()
        first = self._settled(file, 100000)
        second = self._settled(file, 80000)
        file.action_close_operations()
        wizard = self._wizard(file, user=self.biller)
        wizard.debours_line_ids.filtered(
            lambda l: l.expense_id == first).write(
            {'amount_recharged': 120000, 'comment': "uplift"})
        wizard.debours_line_ids.filtered(
            lambda l: l.expense_id == second).write(
            {'amount_recharged': 60000, 'comment': "gesture"})
        wizard.action_submit_for_review()
        file.with_user(self.ops_head).action_approve_recharge_ops()
        file.with_user(self.gm).action_approve_recharge_gm()
        self.assertEqual(file.recharge_state, 'approved')
        # same total, different lines
        wizard = self._wizard(file, user=self.biller)
        wizard.debours_line_ids.filtered(
            lambda l: l.expense_id == first).write(
            {'amount_recharged': 130000, 'comment': "more uplift"})
        wizard.debours_line_ids.filtered(
            lambda l: l.expense_id == second).write(
            {'amount_recharged': 50000, 'comment': "bigger gesture"})
        self.assertTrue(wizard.needs_review,
                        "the approval was for other figures")
        with self.assertRaises(UserError):
            wizard.action_create_invoice()
        wizard.action_submit_for_review()
        self.assertEqual(file.recharge_state, 'requested',
                         "the approval lapsed although the total did not move")
        self.assertFalse(file.recharge_gm_approved_by_id)

    def test_08_a_refusal_bills_at_cost(self):
        file = self._working_file()
        first = self._settled(file, 100000)
        second = self._settled(file, 80000)
        file.action_close_operations()
        wizard = self._wizard(file, user=self.biller)
        wizard.debours_line_ids.filtered(
            lambda l: l.expense_id == first).write(
            {'amount_recharged': 120000, 'comment': "uplift"})
        wizard.debours_line_ids.filtered(
            lambda l: l.expense_id == second).write(
            {'amount_recharged': 60000, 'comment': "gesture"})
        wizard.action_submit_for_review()
        file.with_user(self.ops_head).with_context(
            clearance_rejection_reason="Not agreed with the client"
        ).action_refuse_recharge()
        self.assertEqual(file.recharge_state, 'refused')
        self.assertFalse(first.recharge_amount)
        self.assertFalse(second.recharge_amount)
        self.assertFalse(file._recharge_lines_differ())
        wizard = self._wizard(file, user=self.biller)
        self.assertFalse(wizard.needs_review, "the screen proposes cost again")
        wizard.action_create_invoice()
        self.assertTrue(file.invoice_id)
        charged = {l.clearance_charged for l in file.invoice_id.invoice_line_ids
                   if l.clearance_category == 'debours'}
        self.assertEqual(charged, {100000.0, 80000.0})
