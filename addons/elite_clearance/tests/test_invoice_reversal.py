"""Withdrawing what was billed, and billing a file more than once.

Owner spec 13/09/2026, four instructions: one list of every invoice
issued; a credit note over chosen lines, with the reason first; a
cancellation that books the original entry with the signs the other way
round; and billing a file as costs land rather than once at the end.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestInvoiceReversal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'Z4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.commission = Account.create({
            'code': 'Z70621', 'name': "Commission", 'account_type': 'income'})
        cls.service_fee = Account.create({
            'code': 'Z70622', 'name': "HAD", 'account_type': 'income'})
        cls.undercharge = Account.create({
            'code': 'Z65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.overcharge = Account.create({
            'code': 'Z75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales rev", 'type': 'sale', 'code': 'ZSALR'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.commission.id,
            'clearance_commission_account_id': cls.commission.id,
            'clearance_service_fee_account_id': cls.service_fee.id,
            'clearance_oop_undercharge_account_id': cls.undercharge.id,
            'clearance_oop_overcharge_account_id': cls.overcharge.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash rev", 'type': 'cash', 'code': 'ZCSHR'})
        cls.client = env['res.partner'].create({
            'name': "Reversal Client", 'is_company': True,
            'street': "BP 9999 Douala", 'email': "rev@test.cm",
            'vat': "M000000000009A", 'company_registry': "RC/DLA/2026/B/0009",
            'clearance_invoice_name': "REVERSAL CLIENT SARL"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal Rev", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port rev", 'code': "Z-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Reversal test", 'code': "Z-REV", 'commission_rate': 2.0})

    def setUp(self):
        super().setUp()
        self.file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUZ000001",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': self.client.id,
            'service_type_id': self.service.id})
        self.file.state = 'in_progress'
        self.file.customs_fee_amount = 30000
        self._disburse(60000)
        self._disburse(40000)
        self.file.action_close_operations()

    # ------------------------------------------------------------------
    def _disburse(self, amount, label=None):
        expense = self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': label or ("Handling %d" % amount),
            'amount': amount})
        expense.action_submit()
        expense.action_approve()
        expense.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                       'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        return expense

    def _wizard(self):
        return self.env['logistics.billing.wizard'].with_context(
            active_id=self.file.id).create({})

    def _bill(self):
        self._wizard().action_create_invoice()
        return self.file.invoice_id

    def _credit(self, invoice, picker, reason="Wrong figure agreed with the client."):
        wizard = self.env['logistics.invoice.credit.wizard'].with_context(
            active_id=invoice.id).create({'reason': reason})
        for line in wizard.line_ids:
            line.selected = picker(line)
        wizard.action_create_credit_note()
        return self.env['account.move'].search(
            [('reversed_entry_id', '=', invoice.id)], order='id desc', limit=1)

    # =================================================================
    # 1. every invoice issued, in one list
    # =================================================================
    def test_01_the_invoices_action_lists_invoices_and_credit_notes(self):
        action = self.env.ref('elite_clearance.action_clearance_invoices')
        self.assertEqual(action.res_model, 'account.move')
        domain = safe_eval(action.domain)
        clauses = {clause[0]: clause[2] for clause in domain}
        self.assertIn('logistics_file_id', clauses)
        self.assertEqual(set(clauses['move_type']), {'out_invoice', 'out_refund'},
                         "credit notes belong in the list as much as invoices")
        invoice = self._bill()
        invoice.action_post()
        credit = self._credit(invoice, lambda line: line.amount == 60000)
        found = self.env['account.move'].search(domain)
        self.assertIn(invoice, found)
        self.assertIn(credit, found, "the credit note is an issued document")

    # =================================================================
    # 2. a credit note: the reason first, then the chosen lines
    # =================================================================
    def test_02_a_credit_note_reverses_only_the_lines_chosen(self):
        invoice = self._bill()
        invoice.action_post()
        wizard = self.env['logistics.invoice.credit.wizard'].with_context(
            active_id=invoice.id).create({'reason': "  "})
        # the adjustment line is never offered; every real line is
        self.assertEqual(len(wizard.line_ids), 4,
                         "two disbursements, the commission and the fee")
        with self.assertRaises(UserError, msg="the reason comes first"):
            wizard.action_create_credit_note()
        wizard.reason = "The port invoice was re-issued at a lower figure."
        with self.assertRaises(UserError, msg="and then the lines"):
            wizard.action_create_credit_note()

        credit = self._credit(invoice, lambda line: line.amount == 60000)
        self.assertEqual(credit.move_type, 'out_refund')
        self.assertEqual(credit.state, 'posted', "an unposted reversal reverses nothing")
        self.assertEqual(credit.reversed_entry_id, invoice)
        self.assertEqual(credit.logistics_file_id, self.file)
        self.assertEqual(credit.amount_total, 60000)
        self.assertTrue(credit.name.startswith("AV"), credit.name)
        # the general ledger: what the invoice credited, the note
        # credits again with a minus sign
        self.assertEqual(
            sum(credit.line_ids.filtered(
                lambda l: l.account_id == self.engaged).mapped('credit')),
            -60000)
        self.assertEqual(
            sum(credit.line_ids.filtered(
                lambda l: l.account_id == self.engaged).mapped('debit')),
            0, "it stays on the side the invoice put it")
        self.assertEqual(
            sum(invoice.line_ids.filtered(
                lambda l: l.account_id == self.engaged).mapped('credit')),
            100000, "the other disbursement still stands")
        # and it is set against the invoice, so the receivable is right
        self.assertEqual(invoice.amount_residual,
                         invoice.amount_total - 60000)

    def test_03_a_credited_disbursement_is_billable_again(self):
        invoice = self._bill()
        invoice.action_post()
        billed = self.file.expense_ids.filtered(lambda e: e.amount == 60000)
        self.assertTrue(billed.is_billed)
        self.assertEqual(billed.billed_invoice_id, invoice)
        self.assertFalse(self.file._billable_expenses())
        self.assertFalse(self.file.has_billable)

        self._credit(invoice, lambda line: line.amount == 60000)
        self.assertFalse(billed.is_billed)
        self.assertEqual(self.file._billable_expenses(), billed)
        self.assertTrue(self.file.has_billable)
        # billing it again bills that one and no other
        wizard = self._wizard()
        self.assertEqual(len(wizard.debours_line_ids), 1)
        self.assertEqual(wizard.debours_line_ids.amount_engaged, 60000)
        self.assertEqual(len(wizard.billed_line_ids), 1,
                         "the one that still stands, greyed and unbillable")
        self.assertEqual(wizard.billed_line_ids.amount, 40000)

    def test_04_crediting_a_completed_file_puts_it_back_in_billing(self):
        invoice = self._bill()
        invoice.action_post()
        self.file.action_mark_complete()
        self.assertEqual(self.file.state, 'done')
        self._credit(invoice, lambda line: line.amount == 60000)
        self.assertEqual(self.file.state, 'ops_closed',
                         "a withdrawn bill is a file waiting to be billed")
        self.assertFalse(self.file.date_closed)

    # =================================================================
    # 3. cancelling: the same entry, the other way round
    # =================================================================
    def test_05_cancelling_a_posted_invoice_books_the_negated_entry(self):
        """The same entry again in the SAME columns, with a minus sign -
        not debiting what was credited (owner 13/09/2026)."""
        self.assertTrue(self.env.company.account_storno,
                        "storno accounting is what negates a reversal")
        invoice = self._bill()
        invoice.action_post()
        before = {
            (line.account_id.id, line.debit, line.credit)
            for line in invoice.line_ids if line.account_id}
        wizard = self.env['logistics.invoice.cancel.wizard'].with_context(
            active_id=invoice.id).create({
                'invoice_id': invoice.id,
                'reason': "Billed to the wrong client."})
        wizard.action_cancel_invoice()
        credit = self.env['account.move'].search(
            [('reversed_entry_id', '=', invoice.id)], limit=1)
        self.assertTrue(credit)
        self.assertEqual(credit.state, 'posted')
        after = {
            (line.account_id.id, -line.debit, -line.credit)
            for line in credit.line_ids if line.account_id}
        self.assertEqual(before, after,
                         "every line again, same column, negated")
        # read the other way round: the revenue stays a credit, in red,
        # and the customer stays a debit, in red
        revenue = credit.line_ids.filtered(
            lambda line: line.account_id == self.commission)
        self.assertEqual(revenue.debit, 0)
        self.assertLess(revenue.credit, 0, "negated, not moved to the debit")
        receivable = credit.line_ids.filtered(
            lambda line: line.display_type == 'payment_term')
        self.assertEqual(receivable.credit, 0)
        self.assertLess(receivable.debit, 0)
        # the balances are what they always were, whichever column shows
        self.assertEqual(sum(credit.line_ids.mapped('balance')), 0)
        self.assertEqual(
            sum(invoice.line_ids.mapped('balance'))
            + sum(credit.line_ids.mapped('balance')), 0,
            "the two together come to nothing, which is the point")
        self.assertEqual(invoice.state, 'posted',
                         "a posted entry is not unmade")
        self.assertTrue(invoice.clearance_voided)
        self.assertEqual(invoice.clearance_voided_by_id, self.env.user)
        self.assertEqual(invoice.amount_residual, 0,
                         "the client owes nothing on it")

    def test_06_a_cancelled_invoice_is_no_invoice(self):
        invoice = self._bill()
        invoice.action_post()
        self.file.action_mark_complete()
        self.env['logistics.invoice.cancel.wizard'].create({
            'invoice_id': invoice.id,
            'reason': "Cancelled at the client's request."}).action_cancel_invoice()
        self.assertFalse(invoice._clearance_stands())
        self.assertFalse(self.file.bill_stands)
        self.assertTrue(self.file.has_billable)
        self.assertEqual(self.file.state, 'ops_closed')
        self.assertEqual(len(self.file._billable_expenses()), 2,
                         "both disbursements are free to be billed again")
        # and the screen opens on them
        self.assertEqual(len(self._wizard().debours_line_ids), 2)

    def test_07_cancelling_a_draft_invoice_makes_no_entry(self):
        invoice = self._bill()
        self.assertEqual(invoice.state, 'draft')
        self.env['logistics.invoice.cancel.wizard'].create({
            'invoice_id': invoice.id,
            'reason': "Raised by mistake."}).action_cancel_invoice()
        self.assertEqual(invoice.state, 'cancel')
        self.assertFalse(self.env['account.move'].search(
            [('reversed_entry_id', '=', invoice.id)]),
            "there was no entry to reverse")
        self.assertTrue(self.file.has_billable)

    def test_08_an_invoice_is_cancelled_once(self):
        invoice = self._bill()
        invoice.action_post()
        wizard = self.env['logistics.invoice.cancel.wizard'].create({
            'invoice_id': invoice.id, 'reason': "First."})
        wizard.action_cancel_invoice()
        with self.assertRaises(UserError):
            self.env['logistics.invoice.cancel.wizard'].create({
                'invoice_id': invoice.id,
                'reason': "Again."}).action_cancel_invoice()

    # =================================================================
    # 4. billing a file as the costs land
    # =================================================================
    def test_09_a_later_cost_is_billed_on_a_further_invoice(self):
        first = self._bill()
        first.action_post()
        # more cost lands: the file goes back to operations, and back again
        self.env['logistics.file.reopen.wizard'].create({
            'file_id': self.file.id, 'target_state': 'in_progress',
            'reason': "The demurrage invoice arrived late."}).action_reopen()
        self.assertEqual(self.file.state, 'in_progress')
        late = self._disburse(25000, label="Demurrage")
        self.file.action_close_operations()

        wizard = self._wizard()
        self.assertTrue(wizard.billed_before)
        self.assertEqual(len(wizard.debours_line_ids), 1,
                         "only what has not been billed")
        self.assertEqual(wizard.debours_line_ids.amount_engaged, 25000)
        self.assertEqual(len(wizard.billed_line_ids), 2)
        self.assertEqual(sum(wizard.billed_line_ids.mapped('amount')), 100000)
        # the customs fee was charged on the first invoice and is not
        # proposed again; the commission is charged on the new cost only
        self.assertEqual(wizard.customs_fee_billed, 30000)
        self.assertEqual(wizard.customs_fee_amount, 0)
        self.assertEqual(wizard.commission_amount, 500)

        wizard.action_create_invoice()
        second = self.file.invoice_id
        self.assertNotEqual(second, first)
        self.assertEqual(late.billed_invoice_id, second)
        debours = second.invoice_line_ids.filtered(
            lambda l: l.clearance_category == 'debours')
        self.assertEqual(sum(debours.mapped('price_subtotal')), 25000,
                         "the first invoice's disbursements are not on it")
        self.assertEqual(self.file.invoice_count, 2)
        # the file's declaration fee is untouched by the second screen
        self.assertEqual(self.file.customs_fee_amount, 30000)

    def test_10_nothing_left_to_bill_is_refused(self):
        invoice = self._bill()
        invoice.action_post()
        self.assertFalse(self.file.has_billable)
        with self.assertRaises(UserError):
            self.file.action_open_billing()
        with self.assertRaises(UserError):
            self._wizard().action_create_invoice()

    def test_11_a_file_is_not_complete_while_a_cost_is_unbilled(self):
        first = self._bill()
        first.action_post()
        self.env['logistics.file.reopen.wizard'].create({
            'file_id': self.file.id, 'target_state': 'in_progress',
            'reason': "One more cost."}).action_reopen()
        self._disburse(25000, label="Demurrage")
        self.file.action_close_operations()
        with self.assertRaises(UserError, msg="an unbilled cost is not complete"):
            self.file.action_mark_complete()
        self._wizard().action_create_invoice()
        self.file.invoice_id.action_post()
        self.file.action_mark_complete()
        self.assertEqual(self.file.state, 'done')

    def test_12_balance_due_is_over_every_document(self):
        invoice = self._bill()
        invoice.action_post()
        total = invoice.amount_total
        self.assertEqual(self.file.invoice_balance_due, total)
        self._credit(invoice, lambda line: line.amount == 60000)
        self.assertEqual(self.file.invoice_balance_due, total - 60000,
                         "a credit note reduces what the client owes")

    # =================================================================
    # the printed document
    # =================================================================
    def test_13_a_credit_note_prints_odoos_own_document(self):
        invoice = self._bill()
        invoice.action_post()
        credit = self._credit(invoice, lambda line: line.amount == 60000)
        self.assertEqual(invoice._get_name_invoice_report(),
                         'elite_clearance.report_clearance_invoice_document')
        self.assertEqual(credit._get_name_invoice_report(),
                         'account.report_invoice_document',
                         "the clearance document is an invoice, not a credit note")
