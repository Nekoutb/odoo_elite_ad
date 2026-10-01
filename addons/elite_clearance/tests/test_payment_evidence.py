"""Owner 01/10/2026: the money does not leave without evidence, the
evidence is kept apart from the request documents, and Customer Service
sends it to the third party."""

import base64

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPaymentEvidence(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'P4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        company.write({'clearance_oop_account_id': cls.engaged.id})
        cls.cash = env['account.journal'].create({
            'name': "Cash evidence", 'type': 'cash', 'code': 'PCSH'})
        cls.client = env['res.partner'].create({
            'name': "Evidence Client", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal Evidence", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port evidence", 'code': "P-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Evidence test", 'code': "P-EVD"})
        cls.file = env['logistics.file'].create({
            'customs_regime': 'im4', 'bl_awb_ref': "MEDUP000077",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0, 'partner_id': cls.client.id,
            'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'

        def user(name, group):
            return env['res.users'].create({
                'name': name, 'login': name.lower().replace(' ', '.') + "@evd.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.cashier = user("Evidence Cashier", 'cashier')
        cls.cs_agent = user("Evidence CS", 'customer_service')
        cls.ops_agent = user("Evidence Ops", 'operations')

    def _approved(self):
        """A cash disbursement the Head of Service Finance has signed."""
        exp = self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Handling", 'amount': 50000})
        exp.action_submit()
        exp.action_approve()
        exp.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                   'vendor_id': self.vendor.id})
        exp.action_submit_settlement()
        exp.action_approve_settlement()
        return exp

    def _document(self, name, res_model, res_id):
        return self.env['ir.attachment'].create({
            'name': name, 'res_model': res_model, 'res_id': res_id,
            'datas': base64.b64encode(b"%PDF-1.4 evidence")})

    # =================================================================
    def test_01_nothing_is_paid_out_without_evidence(self):
        exp = self._approved()
        with self.assertRaises(UserError) as caught:
            exp.with_user(self.cashier).action_settle()
        self.assertIn("evidence", str(caught.exception))
        self.assertEqual(exp.state, 'settlement_approved')

        action = exp.with_user(self.cashier).action_open_settle_wizard()
        self.assertEqual(action['res_model'], 'logistics.expense.settle.wizard')
        wizard = self.env['logistics.expense.settle.wizard'].with_user(
            self.cashier).with_context(active_id=exp.id).create({})
        self.assertEqual(wizard.expense_id, exp)
        with self.assertRaises(UserError, msg="the dialog refuses too"):
            wizard.action_pay()

        receipt = self._document("recu-caisse.pdf", wizard._name, wizard.id)
        wizard.write({'attachment_ids': [(4, receipt.id)]})
        wizard.action_pay()
        self.assertEqual(exp.state, 'settled')
        self.assertTrue(exp.date_settled)
        self.assertEqual(receipt.res_model, 'logistics.expense')
        self.assertEqual(receipt.res_id, exp.id)
        self.assertEqual(receipt.clearance_kind, 'payment')
        self.assertEqual(exp.payment_evidence_ids, receipt)

    def test_02_request_documents_and_payment_evidence_are_told_apart(self):
        exp = self._approved()
        quote = self._document("devis.pdf", 'logistics.expense', exp.id)
        exp.invalidate_recordset()
        self.assertEqual(exp.request_document_ids, quote,
                         "a document with no kind is a request document")
        self.assertFalse(exp.payment_evidence_ids)
        self.assertTrue(exp.date_documents_submitted)

        wizard = self.env['logistics.expense.settle.wizard'].with_user(
            self.cashier).with_context(active_id=exp.id).create({})
        receipt = self._document("recu.pdf", wizard._name, wizard.id)
        wizard.write({'attachment_ids': [(4, receipt.id)]})
        wizard.action_pay()
        exp.invalidate_recordset()
        self.assertEqual(exp.request_document_ids, quote)
        self.assertEqual(exp.payment_evidence_ids, receipt)
        self.assertEqual(exp.attachment_ids, quote | receipt,
                         "the chatter and the justification count see one set")
        # removing from the evidence box deletes it, like every other box
        exp.payment_evidence_ids = exp.payment_evidence_ids - receipt
        self.assertFalse(receipt.exists())
        self.assertEqual(exp.request_document_ids, quote,
                         "and leaves the request documents alone")

    def test_03_customer_service_sends_the_evidence_to_the_third_party(self):
        exp = self._approved()
        wizard = self.env['logistics.expense.settle.wizard'].with_context(
            active_id=exp.id).create({})
        receipt = self._document("recu.pdf", wizard._name, wizard.id)
        wizard.write({'attachment_ids': [(4, receipt.id)]})
        wizard.action_pay()

        with self.assertRaises(UserError, msg="not Operations' to send"):
            exp.with_user(self.ops_agent).action_send_payment_evidence()
        with self.assertRaises(UserError) as caught:
            exp.with_user(self.cs_agent).action_send_payment_evidence()
        self.assertIn("e-mail", str(caught.exception))
        self.vendor.email = "compta@terminal-evidence.cm"

        action = exp.with_user(self.cs_agent).action_send_payment_evidence()
        self.assertEqual(action['res_model'], 'mail.compose.message')
        ctx = action['context']
        self.assertEqual(ctx['default_partner_ids'], [(6, 0, self.vendor.ids)])
        self.assertEqual(ctx['default_attachment_ids'], [(6, 0, receipt.ids)])
        self.assertEqual(ctx['default_template_id'], self.env.ref(
            'elite_clearance.mail_template_payment_evidence').id)
        self.assertTrue(ctx['clearance_payment_evidence'])

        # what the composer does on Send, as that user
        composer = self.env['mail.compose.message'].with_user(
            self.cs_agent).with_context(ctx).create({'body': "<p>Ci-joint.</p>"})
        composer._action_send_mail()
        exp.invalidate_recordset()
        self.assertTrue(exp.payment_evidence_sent_date)
        self.assertEqual(exp.payment_evidence_sent_by_id, self.cs_agent)
        sent = exp.message_ids.filtered(lambda m: self.vendor in m.partner_ids)
        self.assertTrue(sent, "the vendor is a recipient of the message")
        self.assertIn(receipt, sent.attachment_ids)
        self.assertEqual(receipt.clearance_kind, 'payment',
                         "sending it does not change what it is")
        self.assertEqual(exp.payment_evidence_ids, receipt)

    def test_04_the_lists_say_when_it_was_paid(self):
        view = self.env.ref('elite_clearance.logistics_file_view_form')
        arch = self.env['logistics.file'].with_user(self.cs_agent).get_view(
            view.id)['arch']
        self.assertIn('date_settled', arch,
                      "Paid On is a column of the file's expense list")
        view = self.env.ref('elite_clearance.logistics_expense_view_list')
        arch = self.env['logistics.expense'].get_view(view.id)['arch']
        self.assertIn('name="date_settled" optional="show"', arch)
