from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReportingAndBillingFix(TransactionCase):
    """The disbursed column cannot be lost, and the clock is measured."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'R4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.income = Account.create({
            'code': 'R7062', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'R6582', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'R7582', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales", 'type': 'sale', 'code': 'RSAL'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.income.id,
            'clearance_commission_account_id': cls.income.id,
            'clearance_service_fee_account_id': cls.income.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash", 'type': 'cash', 'code': 'RCSH'})
        cls.client = env['res.partner'].create({
            'name': "Reporting Client", 'is_company': True})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal R", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port", 'code': "R-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Reporting test", 'code': "R-REP",
            'commission_rate': 2.0})

    def _billable_file(self, amount=566899):
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'partner_id': self.client.id,
            'service_type_id': self.service.id})
        file.state = 'in_progress'
        file.date_started = "2026-09-01 08:00:00"
        expense = self.env['logistics.expense'].create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Diligences douane", 'amount': amount})
        expense.action_submit()
        expense.action_approve()
        expense.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                       'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        file.action_close_operations()
        return file, expense

    def _wizard(self, file):
        return self.env['logistics.billing.wizard'].with_context(
            active_id=file.id).create({})

    # --- the disbursed column ------------------------------------------
    def test_01_disbursed_is_read_from_the_expense(self):
        """It is a fact about the expense, not a copy that can go missing."""
        file, expense = self._billable_file()
        wizard = self._wizard(file)
        line = wizard.debours_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.amount_engaged, 566899)
        self.assertEqual(line.expense_id, expense)

    def test_02_the_disbursed_figure_survives_a_blank_write(self):
        """The web client omits readonly fields; this used to zero them.

        Writing the line without amount_engaged is exactly what the form
        sent back, and it left the column at zero - which then read as a
        variance and demanded an approval nobody had asked for.
        """
        file, _expense = self._billable_file()
        wizard = self._wizard(file)
        wizard.debours_line_ids.write({'amount_recharged': 566899})
        self.assertEqual(wizard.debours_line_ids.amount_engaged, 566899,
                         "the disbursed figure cannot be written away")
        self.assertEqual(wizard.debours_engaged_total, 566899)
        self.assertEqual(wizard.debours_variance, 0)
        self.assertFalse(wizard.needs_review,
                         "billing at cost needs nobody's approval")

    def test_03_billing_at_cost_goes_straight_through(self):
        file, _expense = self._billable_file()
        self._wizard(file).action_create_invoice()
        self.assertTrue(file.invoice_id)
        debours = file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.account_id == self.engaged)
        self.assertEqual(sum(debours.mapped('price_subtotal')), 566899)

    def test_04_only_the_recharge_moves_the_variance(self):
        file, _expense = self._billable_file()
        wizard = self._wizard(file)
        wizard.debours_line_ids.amount_recharged = 400000
        self.assertEqual(wizard.debours_engaged_total, 566899)
        self.assertEqual(wizard.debours_variance, -166899)
        self.assertTrue(wizard.needs_review)

    def test_05_services_are_revenue_and_stay_out_of_the_variance(self):
        """Honoraires are what the company earns, not a cost to recover."""
        file, _expense = self._billable_file()
        wizard = self._wizard(file)
        wizard.customs_fee_amount = 400000
        self.assertEqual(wizard.debours_variance, 0,
                         "a service fee is not a disbursement")
        self.assertFalse(wizard.needs_review)
        self.assertEqual(wizard.service_total, 400000 + 566899 * 0.02)

    # --- approving an adjustment ---------------------------------------
    def test_06_a_written_reason_is_required(self):
        file, _expense = self._billable_file()
        wizard = self._wizard(file)
        wizard.debours_line_ids.amount_recharged = 400000
        with self.assertRaises(UserError):
            wizard.action_submit_for_review()
        wizard.review_reason = "Client disputed the terminal charge."
        wizard.action_submit_for_review()
        self.assertEqual(file.recharge_state, 'requested')

    def test_07_no_attachment_is_demanded(self):
        """Owner 05/09/2026: the explanation is the control, not a file."""
        file, _expense = self._billable_file()
        wizard = self._wizard(file)
        wizard.debours_line_ids.amount_recharged = 400000
        wizard.review_reason = "Agreed with the client in writing."
        wizard.action_submit_for_review()
        self.assertFalse(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'logistics.file'), ('res_id', '=', file.id)]))
        ops = self.env['res.users'].create({
            'name': "Ops Rep", 'login': "ops.rep@rp.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_ops_manager').id])]})
        file.with_user(ops).action_approve_recharge_ops()
        self.assertEqual(file.recharge_state, 'ops_approved',
                         "below cost still needs the General Manager")

    # --- the clock ------------------------------------------------------
    def test_08_the_workflow_stamps_its_own_timestamps(self):
        file, expense = self._billable_file()
        self.assertTrue(file.date_started)
        self.assertTrue(file.date_ops_closed)
        self.assertTrue(expense.date_submitted)
        self.assertTrue(expense.date_settled)
        self._wizard(file).action_create_invoice()
        self.assertTrue(file.date_billed, "billing dates itself")

    def test_09_turnaround_measures_each_step(self):
        file, expense = self._billable_file()
        rows = self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id)])
        self.assertTrue(rows)
        steps = set(rows.mapped('step'))
        for expected in ('file_start', 'exp_submit', 'exp_approve', 'exp_pay'):
            self.assertIn(expected, steps, expected)
        paid = rows.filtered(lambda r: r.step == 'exp_pay')
        self.assertEqual(paid.res_id, expense.id)
        self.assertTrue(paid.is_done)
        self.assertEqual(paid.partner_id, self.client)

    def test_10_an_unfinished_step_measures_against_now(self):
        """A step that has not happened is the one worth chasing."""
        file, _expense = self._billable_file()
        rows = self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id), ('step', '=', 'file_bill')])
        self.assertTrue(rows, "closed for operations, not yet invoiced")
        self.assertFalse(rows.is_done)
        self.assertGreaterEqual(rows.days_taken, 0)

    def test_11_a_target_decides_what_counts_as_late(self):
        file, _expense = self._billable_file()
        target = self.env['clearance.turnaround.target'].search(
            [('step', '=', 'file_ops_close'),
             ('company_id', '=', self.env.company.id)], limit=1)
        self.assertTrue(target, "a target is seeded for every step")
        # the file started on 01/09 and closed today, so a zero-day
        # allowance must read as late and a hundred-day one must not
        target.target_days = 0
        late = self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id), ('step', '=', 'file_ops_close')])
        self.assertTrue(late.is_late)
        target.target_days = 1000
        ontime = self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id), ('step', '=', 'file_ops_close')])
        self.assertFalse(ontime.is_late)

    def test_12_reporting_filters_by_customer_and_by_file(self):
        file_a, _ = self._billable_file()
        other = self.env['res.partner'].create({
            'name': "Second Client", 'is_company': True})
        file_b = self.env['logistics.file'].create({
            'customs_regime': 'im5', 'partner_id': other.id,
            'service_type_id': self.service.id})
        Turnaround = self.env['clearance.turnaround']
        by_customer = Turnaround.search([('partner_id', '=', self.client.id)])
        self.assertTrue(by_customer)
        self.assertNotIn(file_b.id, by_customer.mapped('file_id').ids)
        by_file = Turnaround.search([('file_id', '=', file_a.id)])
        self.assertEqual(set(by_file.mapped('file_id').ids), {file_a.id})

    def test_13_opening_a_measurement_reaches_the_record(self):
        file, expense = self._billable_file()
        row = self.env['clearance.turnaround'].search(
            [('res_id', '=', expense.id),
             ('step', '=', 'exp_pay')], limit=1)
        action = row.action_open()
        self.assertEqual(action['res_model'], 'logistics.expense')
        self.assertEqual(action['res_id'], expense.id)

    def test_14_a_document_wait_is_measured_too(self):
        file, _expense = self._billable_file()
        rows = self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id), ('step', '=', 'doc_receive')])
        self.assertTrue(rows, "the checklist lines are measured as well")
        self.assertEqual(rows[0].res_model, 'logistics.file.document')
        action = rows[0].action_open()
        self.assertEqual(action['res_model'], 'logistics.file',
                         "a checklist line opens its file")
