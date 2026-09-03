from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBillingWizard(TransactionCase):
    """The billing screen: what it proposes, and what it refuses."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'X4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.commission = Account.create({
            'code': 'X70621', 'name': "Commission", 'account_type': 'income'})
        cls.service_fee = Account.create({
            'code': 'X70622', 'name': "HAD", 'account_type': 'income'})
        cls.undercharge = Account.create({
            'code': 'X65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.overcharge = Account.create({
            'code': 'X75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.other_income = Account.create({
            'code': 'X70699', 'name': "Other clearance income",
            'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales", 'type': 'sale', 'code': 'XSAL6'})
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
            'name': "Cash", 'type': 'cash', 'code': 'XCSH6'})
        cls.client = env['res.partner'].create({
            'name': "Wizard Client", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal SA", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port", 'code': "T-PRT6"})
        cls.service = env['logistics.service.type'].create({
            'name': "Wizard test", 'code': "T-WIZ", 'commission_rate': 2.0})
        cls.file = env['logistics.file'].create({
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'
        cls.file.customs_fee_amount = 30000

        def user(name, group):
            return env['res.users'].create({
                'name': name, 'login': name.lower().replace(' ', '.') + "@wiz.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.ops_manager = user("Ops Mgr W", 'ops_manager')
        cls.general_manager = user("Gen Mgr W", 'manager')

        for amount in (60000, 40000):
            exp = env['logistics.expense'].create({
                'file_id': cls.file.id, 'category_id': cls.category.id,
                'description': "Handling %d" % amount, 'amount': amount})
            exp.action_submit()
            exp.action_approve()
            exp.write({'payment_mode': 'cash', 'journal_id': cls.cash.id,
                       'vendor_id': cls.vendor.id})
            exp.action_submit_settlement()
            exp.action_approve_settlement()
            exp.action_settle()
        cls.file.action_close_operations()

    def _wizard(self):
        return self.env['logistics.billing.wizard'].with_context(
            active_id=self.file.id).create({})

    # ------------------------------------------------------------------
    def test_01_the_file_reads_ok_for_billing(self):
        self.assertEqual(self.file.state, 'ops_closed')
        label = dict(self.file._fields['state'].selection)['ops_closed']
        self.assertEqual(label, "OK for Billing")

    def test_02_the_screen_proposes_what_was_disbursed_and_the_two_services(self):
        wizard = self._wizard()
        self.assertEqual(len(wizard.debours_line_ids), 2)
        self.assertEqual(wizard.debours_engaged_total, 100000)
        self.assertEqual(wizard.debours_recharged_total, 100000,
                         "proposed at cost until somebody changes it")
        self.assertEqual(wizard.debours_variance, 0)
        self.assertFalse(wizard.needs_review)
        names = wizard.service_line_ids.mapped('name')
        self.assertTrue(any("Commission sur débours" in n for n in names), names)
        self.assertTrue(any("Honoraires Agréés en Douane" in n for n in names), names)
        self.assertEqual(wizard.service_total, 2000 + 30000)
        self.assertEqual(wizard.invoice_total, 132000)

    def test_03_billing_at_cost_needs_no_approval(self):
        wizard = self._wizard()
        wizard.action_create_invoice()
        invoice = self.file.invoice_id
        self.assertTrue(invoice)
        debours = invoice.invoice_line_ids.filtered(
            lambda l: l.account_id == self.engaged)
        self.assertEqual(sum(debours.mapped('price_subtotal')), 100000)
        self.assertFalse(invoice.invoice_line_ids.filtered(
            lambda l: l.account_id in (self.undercharge, self.overcharge)))

    def test_04_the_biller_may_add_a_service_line(self):
        wizard = self._wizard()
        wizard.service_line_ids = [(0, 0, {
            'name': "Frais de dossier", 'amount': 5000,
            'account_id': self.other_income.id})]
        self.assertEqual(wizard.service_total, 2000 + 30000 + 5000)
        wizard.action_create_invoice()
        extra = self.file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.account_id == self.other_income)
        self.assertEqual(extra.price_subtotal, 5000)
        self.assertEqual(extra.name, "Frais de dossier")

    def test_05_lowering_a_recharge_forces_a_review(self):
        """The biller may change the figure, but not decide it alone."""
        wizard = self._wizard()
        wizard.debours_line_ids[0].amount_recharged = 45000   # was 60,000
        self.assertEqual(wizard.debours_variance, -15000)
        self.assertTrue(wizard.needs_review)
        self.assertEqual(wizard.debours_line_ids[0].variance, -15000)
        with self.assertRaises(UserError):
            wizard.action_create_invoice()
        with self.assertRaises(UserError):
            wizard.action_submit_for_review()          # no reason yet
        wizard.review_reason = "Client disputed the terminal charge."
        wizard.action_submit_for_review()
        self.assertEqual(self.file.recharge_amount, 85000)
        self.assertEqual(self.file.recharge_state, 'requested')
        self.assertFalse(self.file.invoice_id, "no invoice from a review")
        # and the intent is recorded on the disbursement itself
        self.assertEqual(
            self.file._billable_expenses().filtered(
                lambda e: e.amount == 60000).recharge_amount, 45000)

    def test_06_after_both_approvals_the_screen_bills_the_shortfall(self):
        wizard = self._wizard()
        wizard.debours_line_ids[0].amount_recharged = 45000
        wizard.review_reason = "Client disputed the terminal charge."
        wizard.action_submit_for_review()
        self.env['ir.attachment'].create({
            'name': "agreement.pdf", 'res_model': 'logistics.file',
            'res_id': self.file.id, 'raw': b"dummy"})
        self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.file.with_user(self.general_manager).action_approve_recharge_gm()
        self.assertEqual(self.file.recharge_state, 'approved')

        again = self._wizard()
        self.assertEqual(again.debours_recharged_total, 85000,
                         "the screen reopens on the approved figures")
        self.assertFalse(again.needs_review, "the approval stands")
        again.action_create_invoice()
        lines = self.file.invoice_id.invoice_line_ids
        self.assertEqual(
            sum(lines.filtered(lambda l: l.account_id == self.engaged)
                .mapped('price_subtotal')), 100000,
            "47xx still clears at cost")
        under = lines.filtered(lambda l: l.account_id == self.undercharge)
        self.assertEqual(under.price_subtotal, -15000)
        self.assertEqual(
            sum(lines.filtered(lambda l: l.display_type == 'product')
                .mapped('price_subtotal')),
            85000 + 2000 + 30000)

    def test_07_raising_a_recharge_also_goes_for_review(self):
        wizard = self._wizard()
        wizard.debours_line_ids[0].amount_recharged = 70000
        self.assertEqual(wizard.debours_variance, 10000)
        self.assertTrue(wizard.needs_review)
        wizard.review_reason = "Agreed uplift on the terminal charge."
        wizard.action_submit_for_review()
        self.assertEqual(self.file.recharge_state, 'requested')
        # above cost, Operations alone releases it
        self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.assertEqual(self.file.recharge_state, 'approved')
        self._wizard().action_create_invoice()
        over = self.file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.account_id == self.overcharge)
        self.assertEqual(over.price_subtotal, 10000)
