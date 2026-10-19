# -*- coding: utf-8 -*-
"""Legacy uploads (owner's change brief v3, 19/10/2026): the eleven
acceptance tests of section 10, with the figures the brief gives for
files 2026IM0436, 2026IM0433 and 2025IM0691."""
from datetime import date

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .holding import give_holding_account

MIG = {'clearance_migration': True}


@tagged('post_install', '-at_install')
class TestLegacyUploads(TransactionCase):

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
        cls.oop = account('L4716', "Debours engages", 'asset_current', True)
        cls.legacy_oop = account('L471100', "Debours legacy", 'asset_current', True)
        cls.advance = account('L421101', "Personnel avances", 'asset_receivable', True)
        cls.fee = account('L706131', "HAD", 'income')
        cls.commission = account('L706101', "Commission", 'income')
        cls.file_fee = account('L706121', "Ouverture", 'income')
        cls.gain = account('L758801', "Gain debours", 'income_other')
        cls.loss = account('L658801', "Perte debours", 'expense')
        cls.vat = account('L443100', "TVA collectee", 'liability_current')
        cls.misc = env['account.journal'].create({
            'name': "JOD Test", 'type': 'general', 'code': 'LJOD'})
        cls.sale = env['account.journal'].create({
            'name': "Ventes Test", 'type': 'sale', 'code': 'LVTE'})
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
        })
        cls.tax = env['account.tax'].create({
            'name': "TVA 19.25 test", 'amount': 19.25, 'type_tax_use': 'sale'})
        company.clearance_service_tax_ids = [(6, 0, [cls.tax.id])]
        cls.till = env['account.journal'].create({
            'name': "Caisse principale test", 'type': 'cash', 'code': 'LCSH'})
        cls.bank = env['account.journal'].create({
            'name': "AFB test", 'type': 'bank', 'code': 'LAFB'})
        cls.holding = give_holding_account(cls.bank)
        Channel = env['clearance.payment.channel']
        Channel.create({'name': "CAISSE SAGE TEST", 'journal_id': cls.till.id})
        Channel.create({'name': "AFB TEST", 'journal_id': cls.bank.id})

        cls.client = env['res.partner'].create({
            'name': "Client Legacy", 'is_company': True,
            'street': "BP 1 Douala", 'email': "legacy@test.cm",
            'vat': "M000000000111L", 'company_registry': "RC/DLA/2026/B/0111",
            'clearance_invoice_name': "CLIENT LEGACY SA"})
        cls.incomplete = env['res.partner'].create({
            'name': "Client Incomplet", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Migration", 'is_company': True, 'supplier_rank': 1})
        cls.cat = env['logistics.expense.category'].create({
            'name': "KCT test", 'code': "L-KCT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Import legacy test", 'code': "L-IM", 'commission_rate': 0.0})
        cls.port = env['logistics.port'].create({'name': "Douala L"})
        cls.incoterm = env.ref('account.incoterm_CIF')

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@legacy.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.cs_agent = user("CS Agent L", 'customer_service')
        cls.cs_head = user("CS Head L", 'customer_service_manager')
        cls.ops_head = user("Ops Head L", 'ops_manager')
        cls.finance = user("Finance L", 'finance')
        cls.finance_head = user("Finance Head L", 'finance_manager')
        cls.biller = user("Biller L", 'billing')
        cls.employee = env['hr.employee'].create({
            'name': "Agent Avance L", 'user_id': cls.cs_agent.id})

    # ------------------------------------------------------------------
    def _file(self, name, opened, partner=None, complete=True, migrated=True,
              **extra):
        vals = {'name': name, 'partner_id': (partner or self.client).id,
                'service_type_id': self.service.id, 'date_opened': opened,
                'not_containerised': True}
        if complete:
            vals.update({'customs_regime': 'im4', 'bl_awb_ref': "BL" + name,
                         'goods_description': "Marchandises",
                         'cargo_value': 1000000.0, 'package_count': 10,
                         'weight_kg': 500.0, 'shipment_type': 'conventional',
                         'importer_name': "Importateur", 'port_id': self.port.id,
                         'incoterm_id': self.incoterm.id,
                         'cargo_value_currency_id': self.env.company.currency_id.id})
        vals.update(extra)
        File = self.env['logistics.file']
        if migrated:
            File = File.with_context(**MIG)
        return File.create(vals)

    def _load_expense(self, file, amount, target, teese_ref, channel="CAISSE SAGE TEST",
                      accounting='post', paid_on="2026-09-10", advance=False, **extra):
        vals = {'file_id': file.id, 'category_id': self.cat.id,
                'description': teese_ref, 'amount': amount,
                'teese_ref': teese_ref, 'target_state': target,
                'accounting': accounting, 'date_requested': "2026-09-01",
                'date_submitted': "2026-09-01 08:00:00",
                'date_approved': "2026-09-02 08:00:00"}
        if advance:
            vals.update({'payment_mode': 'advance', 'employee_id': self.employee.id})
        else:
            vals['vendor_id'] = self.vendor.id
        if channel:
            vals['teese_channel'] = channel
        if target in ('settled', 'justified'):
            vals['date_settled'] = paid_on + " 10:00:00"
        if target == 'justified':
            vals['date_justified'] = paid_on + " 12:00:00"
        vals.update(extra)
        return self.env['logistics.expense'].with_context(**MIG).create(vals)

    def _load_invoice(self, file, number, debours, services=(), vat=0.0,
                      when="2026-09-15", teese_ref=None, refund=False):
        lines = []
        for name, amount in debours:
            lines.append((0, 0, {'name': name, 'quantity': 1, 'price_unit': amount,
                                 'clearance_category': 'debours',
                                 'tax_ids': [(5, 0, 0)]}))
        for name, amount, kind in services:
            lines.append((0, 0, {'name': name, 'quantity': 1, 'price_unit': amount,
                                 'clearance_category': 'prestation',
                                 'clearance_service_kind': kind,
                                 'tax_ids': [(5, 0, 0)]}))
        if vat:
            lines.append((0, 0, {'name': "TVA", 'quantity': 1, 'price_unit': vat,
                                 'clearance_category': 'vat',
                                 'tax_ids': [(5, 0, 0)]}))
        return self.env['account.move'].with_context(**MIG).create({
            'move_type': 'out_refund' if refund else 'out_invoice',
            'journal_id': self.sale.id, 'partner_id': file.partner_id.id,
            'name': number, 'invoice_date': when, 'invoice_date_due': when,
            'logistics_file_id': file.id, 'teese_ref': teese_ref or number,
            'invoice_line_ids': lines})

    def _result_lines(self, file):
        moves = file._result_moves()
        return moves, {
            'gain': sum(moves.line_ids.filtered(lambda l: l.account_id == self.gain).mapped('credit')),
            'loss': sum(moves.line_ids.filtered(lambda l: l.account_id == self.loss).mapped('debit')),
        }

    # ==================================================================
    def test_01_legacy_file_with_gaps_is_saved_started_and_billed(self):
        file = self._file("2026IM0401", "2026-10-10", partner=self.incomplete,
                          complete=False)
        self.assertTrue(file.legacy_relief, "opened on or before the cutoff")
        self.assertIn("Customs regime", file.missing_fields_display)
        self.assertIn("Customer:", file.missing_fields_display)
        # started without the regime, the cargo or the customer record
        live = file.with_context(clearance_migration=False)
        live.action_start_work()
        self.assertEqual(file.state, 'in_progress')
        exp = self._load_expense(file, 100000, 'settled', "FA-T1")
        live.customs_fee_amount = 50000
        live.action_close_operations()
        self.assertEqual(file.state, 'ops_closed')
        live.action_create_invoice()
        invoices = file._client_invoices()
        self.assertTrue(invoices, "billed with the gaps")
        self.assertEqual(
            invoices.invoice_line_ids.filtered(
                lambda l: l.clearance_category == 'debours').account_id,
            self.legacy_oop, "a legacy file's débours credit 471100")
        self.assertEqual(file.billing_status, 'billed')
        self.assertTrue(file.is_locked)
        self.assertTrue(exp.is_frozen)
        self.assertEqual(exp.billing_round, 1)
        self.assertTrue(file.missing_fields_display, "the banner still lists them")

    def test_02_new_file_with_a_gap_cannot_change_state(self):
        file = self._file("2026IM0902", "2026-10-17", complete=True, migrated=False)
        self.assertFalse(file.legacy_relief)
        file.write({'port_id': False})
        self.assertIn("Port", file.missing_fields_display)
        with self.assertRaises(UserError) as caught:
            file.action_start_work()
        self.assertIn("Port", str(caught.exception))
        self.assertEqual(file.state, 'draft')
        file.write({'port_id': self.port.id})
        file.action_start_work()
        self.assertEqual(file.state, 'in_progress')
        file.customs_fee_amount = 1000
        file.write({'incoterm_id': False})
        with self.assertRaises(UserError):
            file.action_close_operations()
        self.assertEqual(file.state, 'in_progress')

    def test_03_billed_file_refuses_edit_and_delete_everywhere(self):
        file = self._file("2026IM0403", "2026-10-01")
        file.write({'state': 'in_progress'})
        exp = self._load_expense(file, 200000, 'settled', "FA-T3")
        file.customs_fee_amount = 50000
        file.action_close_operations()
        file.action_create_invoice()
        self.assertTrue(file.is_locked)
        plain = file.with_user(self.cs_agent).with_context(clearance_migration=False)
        with self.assertRaises(UserError):
            plain.write({'goods_description': "changed"})       # UI / XML-RPC
        with self.assertRaises(UserError):
            exp.with_user(self.cs_agent).with_context(
                clearance_migration=False).write({'amount': 1})
        with self.assertRaises(UserError):
            exp.with_context(clearance_migration=False).unlink()
        with self.assertRaises(UserError):
            file.with_context(clearance_migration=False).unlink()
        # Odoo's Import is a load(): refused the same way
        with self.assertRaises(UserError):
            self.env['logistics.file'].with_context(clearance_migration=False).browse(
                file.id).write({'importer_name': "X"})
        # the chatter and the internal note stay open
        file.with_context(clearance_migration=False).write({'internal_note': "ok"})
        file.message_post(body="still allowed")
        # the invoice line cannot be reset to draft and edited
        invoice = file.invoice_id
        invoice.action_post()
        with self.assertRaises(UserError):
            invoice.with_context(clearance_migration=False).button_draft()

    def test_04_reopening_for_additional_billing(self):
        file = self._file("2026IM0404", "2026-10-01")
        file.write({'state': 'in_progress'})
        exp1 = self._load_expense(file, 300000, 'settled', "FA-T4a")
        file.customs_fee_amount = 50000
        file.action_close_operations()
        file.action_create_invoice()
        file.invoice_id.action_post()
        file.action_mark_complete()
        self.assertEqual(file.state, 'done')
        self.assertEqual(file.result_status, 'posted', "fully paid: result booked")
        gain_before = file._result_already_posted()
        Wizard = self.env['logistics.file.reopen.wizard'].with_context(
            clearance_migration=False)
        reason = self.env.ref('elite_clearance.reopen_reason_additional_expenditure')
        # without a reason: the field is required (a NOT NULL would
        # poison the test transaction, so the field is what is asserted)
        self.assertTrue(Wizard._fields['reason_id'].required)
        self.assertTrue(Wizard._fields['reason'].required)
        # a plain agent cannot; the Head of Customer Service can
        wizard = Wizard.create({'file_id': file.id, 'reason_id': reason.id,
                                'reason': "Frais de magasinage reçus tard",
                                'target_state': 'in_progress'})
        with self.assertRaises(UserError):
            wizard.with_user(self.cs_agent).action_reopen()
        wizard.with_user(self.cs_head).action_reopen()
        self.assertEqual(file.state, 'in_progress')
        self.assertEqual(file.billing_status, 'reopened')
        self.assertFalse(file.is_locked)
        self.assertTrue(file.completion_required)
        self.assertTrue(file.reopening_ids, "the log")
        self.assertTrue(exp1.is_frozen, "the first round stays frozen")
        with self.assertRaises(UserError):
            exp1.with_context(clearance_migration=False).write({'amount': 2})
        # a new cost in the new round
        exp2 = self._load_expense(file, 100000, 'settled', "FA-T4b")
        self.assertFalse(exp2.is_frozen)
        # re-billing is blocked until the mandatory fields are complete
        file.with_context(clearance_migration=False).write({'port_id': False})
        with self.assertRaises(UserError):
            file.with_context(clearance_migration=False).action_close_operations()
        file.with_context(clearance_migration=False).write({'port_id': self.port.id})
        file.with_context(clearance_migration=False).action_close_operations()
        file.action_create_invoice()
        second = file.invoice_id
        self.assertEqual(file.billing_round, 2)
        self.assertEqual(exp2.billing_round, 2)
        self.assertTrue(exp2.is_frozen)
        debours_lines = second.invoice_line_ids.filtered(
            lambda l: l.clearance_category == 'debours')
        self.assertEqual(len(debours_lines), 1, "only the new round's line")
        self.assertEqual(debours_lines.price_unit, 100000)
        second.action_post()
        self.assertTrue(file.is_locked)
        # only the CHANGE in the result is posted: everything was billed at
        # cost, so the result is nil and nothing is booked twice
        moves, totals = self._result_lines(file)
        self.assertEqual(file._result_already_posted(), file.debours_result)
        self.assertEqual(file.debours_result, gain_before)
        self.assertFalse(moves)
        self.assertEqual(file.result_status, 'posted')

    def test_05_invoice_entry_total_equals_the_teese_total(self):
        file = self._file("2026IM0436", "2026-03-02")
        file.write({'state': 'in_progress'})
        self._load_expense(file, 3000000, 'settled', "FA-T5a", accounting='record_only',
                           paid_on="2026-08-20")
        self._load_expense(file, 1165611, 'settled', "FA-T5b", paid_on="2026-09-05")
        inv = self._load_invoice(
            file, "EL26IM952",
            debours=[("KCT", 3500000), ("Scanner", 1500000), ("Handling", 300000)],
            services=[("HAD", 450000, 'customs_fee')], vat=119753)
        self.assertEqual(inv.state, 'draft')
        file.action_migration_finalize()
        self.assertEqual(inv.state, 'posted', "every TEESE invoice is posted")
        receivable = inv.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable')
        self.assertEqual(sum(receivable.mapped('debit')), 5869753)
        self.assertEqual(inv.amount_total, 5869753)
        # the accounts came from the settings, never from the load
        self.assertEqual(
            inv.invoice_line_ids.filtered(lambda l: l.clearance_category == 'debours')
            .mapped('account_id'), self.legacy_oop)
        self.assertEqual(
            inv.invoice_line_ids.filtered(lambda l: l.clearance_category == 'vat')
            .account_id, self.vat)
        self.assertEqual(
            inv.invoice_line_ids.filtered(lambda l: l.clearance_category == 'prestation')
            .account_id, self.fee)
        self.assertEqual(inv.clearance_entry_type, 'invoice')
        self.assertEqual(file.billing_status, 'billed')
        self.assertTrue(file.is_locked)
        self.assertEqual(file.state, 'done')

    def test_06_fully_paid_file_posts_its_gain(self):
        file = self._file("2026IM0436", "2026-03-02")
        file.write({'state': 'in_progress'})
        self._load_expense(file, 3000000, 'settled', "FA-T6a", accounting='record_only',
                           paid_on="2026-08-20")
        self._load_expense(file, 165611, 'settled', "FA-T6b", paid_on="2026-09-05")
        self._load_invoice(
            file, "EL26IM952",
            debours=[("KCT", 3500000), ("Scanner", 1500000), ("Handling", 300000)],
            services=[("HAD", 450000, 'customs_fee')], vat=119753)
        file.action_migration_finalize()
        self.assertEqual(file.debours_incurred, 3165611)
        self.assertEqual(file.debours_billed, 5000000, "Handling excluded")
        self.assertEqual(file.result_status, 'posted')
        moves, totals = self._result_lines(file)
        self.assertEqual(len(moves), 1)
        self.assertEqual(totals['gain'], 1834389)
        oop_line = moves.line_ids.filtered(lambda l: l.account_id == self.legacy_oop)
        self.assertEqual(oop_line.debit, 1834389)
        self.assertEqual(oop_line.partner_id, self.client)
        self.assertIn("Écart sur débours", moves.ref)
        # idempotent: a second finalize books nothing more
        file.action_migration_finalize()
        self.assertEqual(len(file._result_moves()), 1)

    def test_07_pending_until_the_sage_payment_is_confirmed(self):
        file = self._file("2026IM0433", "2026-02-20")
        file.write({'state': 'in_progress'})
        self._load_expense(file, 1001209, 'settled', "FA-T7a", accounting='record_only',
                           paid_on="2026-08-01")
        kct = self._load_expense(file, 4124791, 'approved', "FA2608811", channel=None,
                                 sage_match="AFD-1827 27/08/2026 proposed")
        self._load_invoice(file, "EL26IM933", debours=[("KCT", 5000000)])
        file.action_migration_finalize()
        self.assertEqual(kct.state, 'approved')
        self.assertEqual(file.result_status, 'pending')
        self.assertFalse(file._result_moves())
        # the accountant confirms the Sage payment
        kct.with_user(self.finance_head).action_confirm_sage_payment(
            "AFD-1827", date(2026, 8, 27))
        self.assertEqual(kct.state, 'settled')
        self.assertEqual(kct.accounting, 'record_only')
        self.assertEqual(kct.sage_payment_ref, "AFD-1827")
        self.assertFalse(kct.settlement_move_id, "no payment entry posted")
        self.assertEqual(file.result_status, 'posted')
        moves, totals = self._result_lines(file)
        self.assertEqual(totals['loss'], 126000)
        self.assertEqual(totals['gain'], 0)
        oop_line = moves.line_ids.filtered(lambda l: l.account_id == self.legacy_oop)
        self.assertEqual(oop_line.credit, 126000)
        self.assertEqual(moves.date, date(2026, 9, 15),
                         "the later of the billing date and the last payment")

    def test_08_skip_gain_loss_posts_nothing(self):
        file = self._file("2025IM0691", "2025-11-03", skip_gain_loss=True)
        file.write({'state': 'in_progress'})
        self._load_expense(file, 500000, 'settled', "FA-T8", accounting='record_only',
                           paid_on="2025-11-10")
        self._load_invoice(file, "EL25IM691", debours=[("KCT", 800000)],
                           when="2025-11-20")
        file.action_migration_finalize()
        self.assertEqual(file.result_status, 'none')
        self.assertFalse(file._result_moves())
        self.assertTrue(file.is_locked)

    def test_09_handling_goes_to_471100_and_not_into_the_result(self):
        file = self._file("2026IM0409", "2026-04-01")
        file.write({'state': 'in_progress'})
        self._load_expense(file, 1000000, 'settled', "FA-T9", paid_on="2026-09-05")
        inv = self._load_invoice(file, "EL26IM909",
                                 debours=[("KCT", 1000000), ("Handling conteneur", 250000)])
        file.action_migration_finalize()
        handling = inv.invoice_line_ids.filtered('is_handling')
        self.assertEqual(len(handling), 1)
        self.assertEqual(handling.account_id, self.legacy_oop)
        self.assertEqual(file.debours_billed, 1000000)
        self.assertEqual(file.debours_result, 0)
        self.assertEqual(file.result_status, 'posted')
        self.assertFalse(file._result_moves(), "nothing to post at zero")

    def test_10_record_only_posts_nothing_and_post_posts_the_payment(self):
        file = self._file("2026IM0410", "2026-05-01")
        file.write({'state': 'in_progress'})
        old = self._load_expense(file, 100000, 'settled', "FA-T10a",
                                 accounting='record_only', paid_on="2026-08-15")
        self.assertEqual(old.state, 'settled')
        self.assertFalse(old.settlement_move_id)
        new = self._load_expense(file, 200000, 'settled', "FA-T10b", paid_on="2026-09-20")
        move = new.settlement_move_id
        self.assertTrue(move)
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.date, date(2026, 9, 20), "dated as the sheet says")
        self.assertEqual(move.journal_id, self.till, "CAISSE SAGE -> Caisse principale")
        debit = move.line_ids.filtered(lambda l: l.debit)
        self.assertEqual(debit.account_id, self.legacy_oop)
        self.assertEqual(debit.partner_id, self.client, "the customer as partner")
        credit = move.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit.account_id, self.till.default_account_id)
        # a bank payment credits the bank's holding account
        bank = self._load_expense(file, 50000, 'settled', "FA-T10c",
                                  channel="AFB TEST", paid_on="2026-09-21")
        self.assertEqual(bank.settlement_move_id.line_ids.filtered(
            lambda l: l.credit).account_id, self.holding)
        # a staff advance reaches 471100 only when justified
        adv = self._load_expense(file, 80000, 'settled', "FA-T10d", advance=True,
                                 paid_on="2026-09-22")
        pay = adv.settlement_move_id
        self.assertEqual(pay.line_ids.filtered(lambda l: l.debit).account_id, self.advance)
        self.assertFalse(adv.justification_move_id)
        adv.with_context(**MIG).write({'target_state': 'justified',
                                       'date_justified': "2026-09-30 10:00:00"})
        self.assertEqual(adv.state, 'justified')
        just = adv.justification_move_id
        self.assertTrue(just)
        self.assertEqual(just.date, date(2026, 9, 30))
        self.assertEqual(just.line_ids.filtered(lambda l: l.debit).account_id, self.legacy_oop)
        self.assertEqual(just.line_ids.filtered(lambda l: l.credit).account_id, self.advance)

    def test_11_loading_twice_duplicates_nothing(self):
        Expense = self.env['logistics.expense'].with_context(**MIG)
        file = self._file("2026IM0411", "2026-06-01")
        file.write({'state': 'in_progress'})
        # the load uses external ids: a second load UPDATES
        self.env['ir.model.data'].create({
            'module': '__import__', 'name': 'teese_file_2026IM0411',
            'model': 'logistics.file', 'res_id': file.id})
        exp = self._load_expense(file, 150000, 'settled', "FA-T11", paid_on="2026-09-10")
        self.env['ir.model.data'].create({
            'module': '__import__', 'name': 'teese_fa_T11',
            'model': 'logistics.expense', 'res_id': exp.id})
        inv = self._load_invoice(file, "EL26IM911", debours=[("KCT", 200000)])
        self.env['ir.model.data'].create({
            'module': '__import__', 'name': 'teese_inv_EL26IM911',
            'model': 'account.move', 'res_id': inv.id})
        file.action_migration_finalize()
        file.action_migration_finalize()
        # a second load of the same rows through load(): updated, not created
        result = Expense.load(
            ['id', 'file_id/id', 'category_id', 'description', 'amount',
             'teese_ref', 'target_state', 'accounting', 'vendor_id'],
            [['__import__.teese_fa_T11', '__import__.teese_file_2026IM0411',
              self.cat.name, "FA-T11", "150000",
              "FA-T11", "settled", "post", self.vendor.name]])
        self.assertFalse(result['messages'], result['messages'])
        self.assertEqual(result['ids'], [exp.id])
        self.assertEqual(self.env['logistics.expense'].search_count(
            [('teese_ref', '=', "FA-T11")]), 1)
        self.assertEqual(self.env['account.move'].search_count(
            [('logistics_file_id', '=', file.id),
             ('clearance_entry_type', '=', 'payment')]), 1,
            "the payment entry was posted once")
        self.assertEqual(self.env['account.move'].search_count(
            [('teese_ref', '=', "EL26IM911")]), 1)
        self.assertEqual(len(file._result_moves()), 1)
