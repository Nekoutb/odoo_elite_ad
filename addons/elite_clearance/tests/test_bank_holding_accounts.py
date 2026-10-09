"""Owner spec 09/10/2026: each bank has its own holding account.

A disbursement paid through a bank, Mobile Money or Maviance journal is
credited to that journal's Outstanding Payments account, not to the bank
account. The bank account moves only when the statement line is matched,
which clears the holding account. A till is still credited directly.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .holding import give_holding_account


@tagged('post_install', '-at_install')
class TestBankHoldingAccounts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'W4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.advances = Account.create({
            'code': 'W421101', 'name': "Personnel debours avances",
            'account_type': 'asset_current', 'reconcile': True})
        cls.payable = Account.create({
            'code': 'W401100', 'name': "Suppliers",
            'account_type': 'liability_payable', 'reconcile': True})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advances.id,
        })
        Journal = env['account.journal']
        cls.cash = Journal.create({
            'name': "Caisse W", 'type': 'cash', 'code': 'WCSH'})
        cls.bank = Journal.create({
            'name': "Banque A W", 'type': 'bank', 'code': 'WBKA'})
        cls.holding = give_holding_account(cls.bank)
        cls.other_bank = Journal.create({
            'name': "Banque B W", 'type': 'bank', 'code': 'WBKB'})
        cls.other_bank.outbound_payment_method_line_ids.payment_account_id = False
        cls.vendor = env['res.partner'].create({
            'name': "Terminal W", 'is_company': True, 'supplier_rank': 1})
        cls.vendor.property_account_payable_id = cls.payable
        cls.employee = env['hr.employee'].create({'name': "Field Agent W"})
        cls.category = env['logistics.expense.category'].create({
            'name': "Terminal W", 'code': "T-WTR"})
        cls.service = env['logistics.service.type'].create({
            'name': "Holding test", 'code': "T-WHL", 'commission_rate': 2.0})
        cls.client = env['res.partner'].create({
            'name': "Client W", 'is_company': True})
        cls.file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW009910",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'

    def _approved(self, amount, journal, advance=False):
        exp = self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Manutention", 'amount': amount})
        exp.action_submit()
        exp.action_approve()
        vals = {'journal_id': journal.id}
        if advance:
            vals.update(payment_mode='advance', employee_id=self.employee.id)
        else:
            vals['vendor_id'] = self.vendor.id
        exp.write(vals)
        exp.action_submit_settlement()
        exp.action_approve_settlement()
        return exp

    def _paid(self, amount, journal, advance=False):
        exp = self._approved(amount, journal, advance)
        exp.action_settle()
        return exp

    def _lines(self, exp, account):
        return exp.settlement_move_id.line_ids.filtered(
            lambda l: l.account_id == account)

    def test_01_a_bank_payment_credits_the_banks_holding_account(self):
        exp = self._paid(250000, self.bank)
        self.assertFalse(self._lines(exp, self.bank.default_account_id),
                         "the bank account waits for the statement")
        held = self._lines(exp, self.holding)
        self.assertEqual(held.credit, 250000)
        self.assertEqual(held.partner_id, self.vendor,
                         "the vendor on the line is what the statement "
                         "matching proposes on")
        payable = self._lines(exp, self.payable)
        self.assertEqual(sum(payable.mapped('debit')), sum(payable.mapped('credit')),
                         "the vendor is paid the day Finance pays")

    def test_02_an_advance_by_bank_is_held_against_the_holder(self):
        exp = self._paid(80000, self.bank, advance=True)
        held = self._lines(exp, self.holding)
        self.assertEqual(held.credit, 80000)
        self.assertEqual(held.partner_id,
                         self.employee._clearance_auxiliary_partner())
        self.assertEqual(self._lines(exp, self.advances).debit, 80000)

    def test_03_a_till_is_still_credited_directly(self):
        exp = self._paid(15000, self.cash)
        self.assertEqual(
            self._lines(exp, self.cash.default_account_id).credit, 15000)

    def test_04_a_bank_without_its_holding_account_cannot_pay(self):
        exp = self._approved(40000, self.other_bank)
        with self.assertRaisesRegex(UserError, "Outstanding Payments"):
            exp.action_open_settle_wizard()
        with self.assertRaisesRegex(UserError, "Outstanding Payments"):
            exp.action_settle()
        self.assertEqual(exp.state, 'settlement_approved')
        self.assertFalse(exp.settlement_move_id)

    def test_05_a_holding_account_is_one_banks_alone(self):
        self.other_bank.outbound_payment_method_line_ids.payment_account_id = self.holding
        exp = self._approved(40000, self.other_bank)
        with self.assertRaisesRegex(UserError, "also used by"):
            exp.action_settle()

    def test_06_it_must_be_reconcilable_and_not_the_bank_account(self):
        lines = self.other_bank.outbound_payment_method_line_ids
        lines.payment_account_id = self.other_bank.default_account_id
        exp = self._approved(40000, self.other_bank)
        with self.assertRaisesRegex(UserError, "must be reconcilable"):
            exp.action_settle()
        plain = self.env['account.account'].create({
            'code': 'W5899', 'name': "Not reconcilable",
            'account_type': 'asset_current', 'reconcile': False})
        lines.payment_account_id = plain
        with self.assertRaisesRegex(UserError, "must be reconcilable"):
            exp.action_settle()

    def test_07_the_statement_clears_the_holding_account(self):
        """What the matched statement line posts: Dr holding / Cr bank.
        Reconciled against the settlement, the holding account is clear
        and the bank account has been credited exactly once."""
        exp = self._paid(250000, self.bank)
        bank_account = self.bank.default_account_id
        cleared = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.bank.id,
            'line_ids': [
                (0, 0, {'account_id': self.holding.id,
                        'partner_id': self.vendor.id, 'debit': 250000}),
                (0, 0, {'account_id': bank_account.id,
                        'partner_id': self.vendor.id, 'credit': 250000}),
            ]})
        cleared.action_post()
        pair = self._lines(exp, self.holding) | cleared.line_ids.filtered(
            lambda l: l.account_id == self.holding)
        pair.reconcile()
        self.assertTrue(all(pair.mapped('reconciled')))
        self.assertEqual(sum(pair.mapped('balance')), 0)
        moved = self.env['account.move.line'].search([
            ('account_id', '=', bank_account.id),
            ('move_id', 'in', (exp.settlement_move_id | cleared).ids)])
        self.assertEqual(sum(moved.mapped('balance')), -250000)
