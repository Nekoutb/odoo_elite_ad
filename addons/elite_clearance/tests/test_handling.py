# -*- coding: utf-8 -*-
"""Handling billed and due to the customer (owner's change brief,
20/10/2026): the acceptance tests of its section 7, with the figures the
brief gives for file 2026IM0110 and invoice EL26IM252."""
from datetime import date

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..hooks import seed_handling_service
from ..models.handling import HANDLING_LABEL, HANDLING_SERVICE_NAME
from .holding import give_holding_account

MIG = {'clearance_migration': True}


@tagged('post_install', '-at_install')
class TestHandling(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']

        def account(code, name, kind, reconcile=False):
            return Account.create({'code': code, 'name': name,
                                   'account_type': kind, 'reconcile': reconcile})
        cls.oop = account('H4716', "Debours engages", 'asset_current', True)
        cls.legacy_oop = account('H471100', "Debours legacy", 'asset_current', True)
        cls.advance = account('H421101', "Personnel avances", 'asset_receivable', True)
        cls.fee = account('H706131', "HAD", 'income')
        cls.commission = account('H706101', "Commission", 'income')
        cls.file_fee = account('H706121', "Ouverture", 'income')
        cls.gain = account('H758801', "Gain debours", 'income_other')
        cls.loss = account('H658801', "Perte debours", 'expense')
        cls.vat = account('H443100', "TVA collectee", 'liability_current')
        cls.bank_account = account('H521100', "Banque", 'asset_cash')
        cls.customer_credit = account('H419100', "Clients, avoirs a rembourser",
                                      'liability_current', True)
        cls.misc = env['account.journal'].create({
            'name': "JOD Handling", 'type': 'general', 'code': 'HJOD'})
        cls.sale = env['account.journal'].create({
            'name': "Ventes Handling", 'type': 'sale', 'code': 'HVTE'})
        company.write({
            'clearance_oop_account_id': cls.oop.id,
            'clearance_legacy_oop_account_id': cls.legacy_oop.id,
            'clearance_advance_account_id': cls.advance.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_commission_account_id': cls.commission.id,
            'clearance_service_fee_account_id': cls.fee.id,
            'clearance_file_fee_account_id': cls.file_fee.id,
            'clearance_oop_gain_account_id': cls.gain.id,
            'clearance_oop_loss_account_id': cls.loss.id,
            'clearance_vat_account_id': cls.vat.id,
            'clearance_misc_journal_id': cls.misc.id,
            'clearance_sale_journal_id': cls.sale.id,
            'clearance_oop_payable_account_id': False,
            'clearance_handling_account_id': False,
        })
        cls.tax = env['account.tax'].create({
            'name': "TVA 19.25 handling", 'amount': 19.25, 'type_tax_use': 'sale'})
        company.clearance_service_tax_ids = [(6, 0, [cls.tax.id])]
        cls.till = env['account.journal'].create({
            'name': "Caisse handling", 'type': 'cash', 'code': 'HCSH'})
        cls.bank = env['account.journal'].create({
            'name': "AFB handling", 'type': 'bank', 'code': 'HAFB'})
        cls.holding = give_holding_account(cls.bank)
        env['clearance.payment.channel'].create({
            'name': "CAISSE HANDLING", 'journal_id': cls.till.id})

        cls.client = env['res.partner'].create({
            'name': "Client Handling", 'is_company': True,
            'street': "BP 2 Douala", 'email': "handling@test.cm",
            'vat': "M000000000222H", 'company_registry': "RC/DLA/2026/B/0222",
            'clearance_invoice_name': "CLIENT HANDLING SA",
            # the brief's figures carry no VAT on the services
            'clearance_vat_exempt': True})
        cls.receivable = cls.client.property_account_receivable_id
        cls.vendor = env['res.partner'].create({
            'name': "Migration H", 'is_company': True, 'supplier_rank': 1})
        cls.cat = env['logistics.expense.category'].create({
            'name': "KCT handling", 'code': "H-KCT"})
        cls.cat_handling = env['logistics.expense.category'].create({
            'name': "Handling (catégorie)", 'code': "H-HAND", 'is_handling': True})
        cls.service = env['logistics.service.type'].create({
            'name': "Import handling test", 'code': "H-IM", 'commission_rate': 0.0})
        cls.port = env['logistics.port'].create({'name': "Douala H"})
        cls.incoterm = env.ref('account.incoterm_CIF')
        seed_handling_service(env)
        cls.hand = env['logistics.billing.service'].search([
            ('name', '=', HANDLING_SERVICE_NAME),
            ('company_id', '=', company.id)], limit=1)

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@handling.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.cs_agent = user("CS Agent H", 'customer_service')
        cls.biller = user("Biller H", 'billing')
        cls.finance_head = user("Finance Head H", 'finance_manager')
        cls.employee = env['hr.employee'].create({
            'name': "Agent H", 'user_id': cls.cs_agent.id})

    # ------------------------------------------------------------------
    def _file(self, name, opened, **extra):
        vals = {'name': name, 'partner_id': self.client.id,
                'service_type_id': self.service.id, 'date_opened': opened,
                'not_containerised': True,
                'customs_regime': 'im4', 'bl_awb_ref': "BL" + name,
                'goods_description': "Marchandises",
                'cargo_value': 1000000.0, 'package_count': 10,
                'weight_kg': 500.0, 'shipment_type': 'conventional',
                'importer_name': "Importateur", 'port_id': self.port.id,
                'incoterm_id': self.incoterm.id,
                'cargo_value_currency_id': self.env.company.currency_id.id}
        vals.update(extra)
        file = self.env['logistics.file'].with_context(**MIG).create(vals)
        file.write({'state': 'in_progress'})
        return file

    def _load_expense(self, file, amount, teese_ref, paid_on="2026-09-10"):
        return self.env['logistics.expense'].with_context(**MIG).create({
            'file_id': file.id, 'category_id': self.cat.id,
            'description': teese_ref, 'amount': amount,
            'teese_ref': teese_ref, 'target_state': 'settled',
            'accounting': 'post', 'vendor_id': self.vendor.id,
            'teese_channel': "CAISSE HANDLING",
            'date_requested': "2026-09-01",
            'date_submitted': "2026-09-01 08:00:00",
            'date_approved': "2026-09-02 08:00:00",
            'date_settled': paid_on + " 10:00:00"})

    def _load_invoice(self, file, number, debours=(), services=(),
                      when="2026-09-15", refund=False):
        lines = []
        for row in debours:
            lines.append((0, 0, {'name': row[0], 'quantity': 1, 'price_unit': row[1],
                                 'clearance_category': 'debours',
                                 'is_handling': bool(row[2]) if len(row) > 2 else False,
                                 'tax_ids': [(5, 0, 0)]}))
        for name, amount, kind in services:
            lines.append((0, 0, {'name': name, 'quantity': 1, 'price_unit': amount,
                                 'clearance_category': 'prestation',
                                 'clearance_service_kind': kind,
                                 'tax_ids': [(5, 0, 0)]}))
        return self.env['account.move'].with_context(**MIG).create({
            'move_type': 'out_refund' if refund else 'out_invoice',
            'journal_id': self.sale.id, 'partner_id': file.partner_id.id,
            'name': number, 'invoice_date': when, 'invoice_date_due': when,
            'logistics_file_id': file.id, 'teese_ref': number,
            'invoice_line_ids': lines})

    def _bill_with_handling(self, name="2026IM0902", handling=25000000):
        """A new bill through the billing screen: 100,000,000 of
        disbursements, 15,063,028 of customs fee and the Handling
        component - the brief's 140,063,028."""
        file = self._file(name, "2026-09-01")
        self._load_expense(file, 100000000, "FA-H-" + name)
        live = file.with_context(clearance_migration=False)
        live.customs_fee_amount = 15063028
        live.action_close_operations()
        self.assertEqual(file.state, 'ops_closed')
        wizard = self.env['logistics.billing.wizard'].with_user(
            self.biller).with_context(active_id=file.id).create({
                'service_line_ids': [fields.Command.create({
                    'service_id': self.hand.id, 'name': self.hand.name,
                    'amount': handling})]})
        self.assertTrue(wizard.service_line_ids.filtered('is_handling'),
                        "the screen knows the component is Handling")
        wizard.action_create_invoice()
        invoice = file.invoice_id
        self.assertEqual(invoice.state, 'draft')
        invoice.action_post()
        return file, invoice

    def _term_line(self, move):
        return move.line_ids.filtered(lambda l: l.display_type == 'payment_term')

    # ==================================================================
    def test_01_settings_decide_the_handling_account(self):
        company = self.env.company
        self.assertFalse(company.clearance_handling_account_id)
        self.assertEqual(company._clearance_handling_account(self.client),
                         self.receivable, "empty = the customer's own receivable")
        # a dedicated account: credited there, the customer as partner,
        # nothing matched inside the entry
        company.clearance_handling_account_id = self.customer_credit
        file, invoice = self._bill_with_handling("2026IM0901")
        handling = invoice.invoice_line_ids.filtered('is_handling')
        self.assertEqual(len(handling), 1)
        self.assertEqual(handling.account_id, self.customer_credit)
        self.assertEqual(handling.partner_id, self.client)
        self.assertEqual(handling.credit, 25000000)
        self.assertFalse(handling.reconciled)
        self.assertEqual(invoice.amount_total, 140063028)
        self.assertEqual(invoice.amount_residual, 140063028,
                         "the invoice is owed in full; the accountant "
                         "refunds or offsets the Handling account")
        company.clearance_handling_account_id = False

    def test_02_billing_the_handling_component(self):
        file, invoice = self._bill_with_handling()
        self.assertEqual(invoice.amount_total, 140063028)
        term = self._term_line(invoice)
        self.assertEqual(len(term), 1)
        self.assertEqual(term.account_id, self.receivable)
        self.assertEqual(term.debit, 140063028, "Dr 411100 for the full total")
        handling = invoice.invoice_line_ids.filtered('is_handling')
        self.assertEqual(len(handling), 1)
        self.assertEqual(handling.account_id, self.receivable, "Cr 411100")
        self.assertEqual(handling.credit, 25000000)
        self.assertEqual(handling.partner_id, self.client)
        self.assertFalse(handling.tax_ids)
        self.assertTrue(handling.reconciled, "matched inside the entry")
        self.assertEqual(invoice.amount_residual, 115063028,
                         "open balance = total - Handling")
        self.assertEqual(invoice.payment_state, 'not_paid',
                         "the match inside the entry is not a payment")
        self.assertFalse(invoice._get_all_reconciled_invoice_partials())
        self.assertFalse(invoice.invoice_payments_widget)
        # nothing on 471100, revenue or VAT for the Handling
        others = invoice.line_ids.filtered(
            lambda l: l.account_id in (self.legacy_oop | self.oop | self.fee
                                       | self.commission | self.vat))
        self.assertFalse(others.filtered('is_handling'))
        self.assertEqual(sum(others.mapped('credit')), 115063028)
        # the ledger label and the printed wording
        self.assertEqual(handling.name, "%s | %s | %s" % (
            file.name, invoice.name, HANDLING_LABEL))
        self.assertEqual(handling.clearance_print_name, HANDLING_SERVICE_NAME)
        self.assertEqual(handling.clearance_service_kind, 'handling')
        # the file's summary
        self.assertEqual(file.handling_billed, 25000000)
        self.assertEqual(file.debours_billed, 100000000)
        self.assertTrue(file.is_locked)
        # the flag of a posted line is not editable
        with self.assertRaisesRegex(UserError, "cannot be changed"):
            handling.is_handling = False

    def test_03_migrated_invoice_its_correction_and_the_result(self):
        # acceptance tests 3 and 4: file 2026IM0110
        file = self._file("2026IM0110", "2026-03-01")
        self._load_expense(file, 110782375, "FA-H-0110", paid_on="2026-09-05")
        inv = self._load_invoice(
            file, "EL26IM252",
            debours=[("KCT", 114583208), ("Handling conteneur", 25080000, True)],
            services=[("Frais divers", 399820, 'other')])
        self.assertEqual(inv.amount_total, 140063028)
        # a negative total cannot be posted in Odoo: the correction is
        # loaded as the credit note it is, and the sides swap by themselves
        corr = self._load_invoice(file, "EL26IM269",
                                  debours=[("Handling correction", 80000, True)],
                                  when="2026-09-20", refund=True)
        file.action_migration_finalize()
        self.assertEqual(inv.state, 'posted')
        handling = inv.invoice_line_ids.filtered('is_handling')
        self.assertEqual(handling.account_id, self.receivable)
        self.assertTrue(handling.reconciled)
        self.assertEqual(inv.amount_residual, 114983028)
        self.assertEqual(corr.state, 'posted')
        corr_line = corr.invoice_line_ids.filtered('is_handling')
        self.assertEqual(corr_line.debit, 80000, "sides swapped")
        self.assertEqual(corr_line.account_id, self.receivable)
        self.assertTrue(corr_line.reconciled)
        self.assertEqual(corr.amount_residual, 0)
        self.assertEqual(file.handling_billed, 25000000)
        # the débours result, Handling outside it on both sides
        self.assertEqual(file.debours_billed, 114583208)
        self.assertEqual(file.debours_incurred, 110782375)
        self.assertEqual(file.debours_result, 3800833)
        self.assertEqual(file.result_status, 'posted')
        moves = file._result_moves()
        gain = sum(moves.line_ids.filtered(
            lambda l: l.account_id == self.gain).mapped('credit'))
        self.assertEqual(gain, 3800833)
        self.assertFalse(moves.line_ids.filtered('is_handling'))

    def test_04_no_disbursement_and_no_vat_under_handling(self):
        file = self._file("2026IM0904", "2026-09-01")
        with self.assertRaisesRegex(ValidationError, "Handling component"):
            self.env['logistics.expense'].with_context(**MIG).create({
                'file_id': file.id, 'category_id': self.cat_handling.id,
                'description': "jamais", 'amount': 1000,
                'vendor_id': self.vendor.id})
        # a VAT rate on a flagged line is refused at once
        with self.assertRaisesRegex(ValidationError, "no VAT"):
            self.env['account.move'].create({
                'move_type': 'out_invoice', 'journal_id': self.sale.id,
                'partner_id': self.client.id, 'logistics_file_id': file.id,
                'invoice_line_ids': [(0, 0, {
                    'name': "Handling", 'quantity': 1, 'price_unit': 1000,
                    'account_id': self.receivable.id, 'is_handling': True,
                    'tax_ids': [(6, 0, [self.tax.id])]})]})
        # and a Handling line that lands anywhere but the Handling
        # account is refused at posting
        wrong = self.env['account.move'].create({
            'move_type': 'out_invoice', 'journal_id': self.sale.id,
            'partner_id': self.client.id, 'logistics_file_id': file.id,
            'invoice_date': "2026-09-15",
            'invoice_line_ids': [(0, 0, {
                'name': "Handling", 'quantity': 1, 'price_unit': 1000,
                'account_id': self.legacy_oop.id, 'is_handling': True,
                'clearance_category': 'debours', 'tax_ids': [(5, 0, 0)]})]})
        with self.assertRaisesRegex(UserError, "may only be credited"):
            wrong.action_post()
        self.assertEqual(wrong.state, 'draft')

    def test_05_the_customer_pays_the_gross_amount(self):
        file, invoice = self._bill_with_handling("2026IM0905")
        receipt = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.misc.id,
            'date': "2026-09-30", 'ref': "Virement %s" % invoice.name,
            'line_ids': [
                (0, 0, {'account_id': self.bank_account.id,
                        'partner_id': self.client.id, 'debit': 140063028}),
                (0, 0, {'account_id': self.receivable.id,
                        'partner_id': self.client.id, 'credit': 140063028})]})
        receipt.action_post()
        paid = receipt.line_ids.filtered(lambda l: l.account_id == self.receivable)
        (paid | self._term_line(invoice)).reconcile()
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(invoice.payment_state, 'paid')
        self.assertFalse(paid.reconciled)
        self.assertEqual(paid.amount_residual, -25000000,
                         "the excess stays as a credit on the customer")

    def test_06_a_credit_note_on_the_handling_line(self):
        file, invoice = self._bill_with_handling("2026IM0906")
        handling = invoice.invoice_line_ids.filtered('is_handling')
        credit = invoice._clearance_raise_credit_note(handling, "Handling withdrawn")
        self.assertEqual(credit.state, 'posted')
        reversed_line = credit.invoice_line_ids.filtered('is_handling')
        self.assertEqual(len(reversed_line), 1)
        self.assertEqual(reversed_line.account_id, self.receivable)
        self.assertEqual(reversed_line.debit, 25000000, "the credit reversed")
        self.assertTrue(reversed_line.reconciled)
        self.assertEqual(credit.amount_residual, 0)
        self.assertEqual(invoice.amount_residual, 115063028,
                         "the charge and the credit go together: the open "
                         "balance does not move")
        self.assertEqual(file.handling_billed, 0)

    def test_07_the_report_lists_what_is_due(self):
        file, invoice = self._bill_with_handling("2026IM0907")
        action = self.env.ref('elite_clearance.action_clearance_handling_due')
        self.assertEqual(action.res_model, 'account.move.line')
        lines = self.env['account.move.line'].search(
            [('clearance_file_id', '=', file.id)] + [
                ('is_handling', '=', True), ('parent_state', '=', 'posted'),
                ('display_type', '=', 'product')])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.clearance_handling_amount, 25000000)
        self.assertEqual(lines.partner_id, self.client)
        self.assertEqual(lines.clearance_invoice_payment_state, 'not_paid')
        self.assertEqual(lines.date, invoice.date)
        menu = self.env.ref('elite_clearance.menu_clearance_handling_due')
        self.assertEqual(menu.action.id, action.id)
