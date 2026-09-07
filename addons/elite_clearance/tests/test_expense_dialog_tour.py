from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestExpenseDialogTour(HttpCase):
    """The expense capture dialog in a real browser.

    Drives static/tests/tours/expense_dialog_tour.js as an Operations
    agent: open the dialog from the file, type the amount, pick the
    vendor, drop a receipt on the dialog, save. Then checks what reached
    the database. Needs Chromium on the machine running the suite; CI
    installs it and refuses a run in which this test was skipped.
    """

    def test_01_amount_vendor_and_a_dropped_receipt_from_the_dialog(self):
        env = self.env
        client = env['res.partner'].create({
            'name': "Tour Client", 'is_company': True,
            'street': "BP 1234 Douala", 'email': "client@test.cm",
            'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001"})
        vendor = env['res.partner'].create({
            'name': "Douala Terminal Tour", 'is_company': True})
        category = env['logistics.expense.category'].create({
            'name': "Tour terminal fees", 'code': "T-TOUR"})
        service = env['logistics.service.type'].create({
            'name': "Tour service", 'code': "T-TOUR"})
        file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW000042",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': client.id, 'service_type_id': service.id})
        file.state = 'in_progress'
        login = "ops.tour@clearance.test"
        env['res.users'].create({
            'name': "Ops Tour", 'login': login, 'password': login,
            'group_ids': [(6, 0, [env.ref(
                'elite_clearance.group_clearance_operations').id])]})

        self.start_tour(
            "/odoo/action-elite_clearance.action_logistics_file/%d" % file.id,
            "elite_clearance_expense_dialog", login=login)

        expense = env['logistics.expense'].search([('file_id', '=', file.id)])
        self.assertEqual(len(expense), 1, "one expense keyed from the dialog")
        self.assertEqual(expense.description, "Terminal handling")
        self.assertEqual(expense.amount, 25000)
        self.assertEqual(expense.category_id, category)
        self.assertEqual(expense.vendor_id, vendor,
                         "the vendor was picked in the dialog")
        self.assertEqual(expense.state, 'draft')
        self.assertEqual(expense.unit_label, "Par dossier")
        receipts = env['ir.attachment'].search([
            ('res_model', '=', 'logistics.expense'),
            ('res_id', '=', expense.id)])
        self.assertEqual(receipts.mapped('name'), ["receipt.txt"],
                         "the dropped file is the expense's document")
        self.assertEqual(receipts, expense.attachment_ids)
        self.assertTrue(expense.date_documents_submitted)
        self.assertEqual(receipts.create_uid.login, login,
                         "uploaded by the agent, not by anyone else")
