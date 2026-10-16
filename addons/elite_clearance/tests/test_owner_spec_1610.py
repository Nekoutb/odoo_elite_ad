"""Owner spec 16/10/2026, second message: the overall turnaround time
(commercial invoice received -> delivered), the transit time per
service type, the manifesting vendors and their date, the delivery
date at justification."""

from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec1610(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'E4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.advance = Account.create({
            'code': 'E421101', 'name': "Personnel debours avances",
            'account_type': 'asset_receivable', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'E70621', 'name': "Fees", 'account_type': 'income'})
        cls.misc = env['account.journal'].create({
            'name': "Misc 1610", 'type': 'general', 'code': 'EMSC'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advance.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_misc_journal_id': cls.misc.id,
        })
        cls.till = env['account.journal'].create({
            'name': "Caisse 1610", 'type': 'cash', 'code': 'ECSH'})
        cls.client = env['res.partner'].create({
            'name': "Edea Aluminium", 'is_company': True,
            'street': "BP 12 Edea", 'email': "alu@test.cm",
            'vat': "M000000000091E", 'company_registry': "RC/EDE/2026/B/0091",
            'clearance_invoice_name': "EDEA ALUMINIUM SA"})
        cls.line = env['res.partner'].create({
            'name': "MSC Cameroun Test", 'is_company': True, 'supplier_rank': 1})
        cls.terminal = env['res.partner'].create({
            'name': "Terminal Test 1610", 'is_company': True, 'supplier_rank': 1})
        company.clearance_manifesting_vendor_ids = [(6, 0, [cls.line.id])]
        cls.cat_port = env['logistics.expense.category'].create({
            'name': "Frais de ligne", 'code': "E-LIN"})
        cls.cat_transport = env['logistics.expense.category'].create({
            'name': "Transport livraison test", 'code': "E-TLV"})
        DocType = env['logistics.document.type']
        cls.doc_inv = DocType.search([('code', '=', 'INV')], limit=1)
        assert cls.doc_inv, "the seeded commercial invoice document type"
        cls.doc_other = DocType.create({'name': "Autre pièce test", 'code': "E-OTH"})
        cls.service = env['logistics.service.type'].create({
            'name': "Import test 1610", 'code': "E-IMT",
            'transit_start_rule': 'later', 'transit_end_rule': 'vendor_paid',
            'document_ids': [
                (0, 0, {'document_type_id': cls.doc_inv.id, 'is_mandatory': True}),
                (0, 0, {'document_type_id': cls.doc_other.id, 'is_mandatory': True})]})
        cls.no_rule = env['logistics.service.type'].create({
            'name': "Sans règle 1610", 'code': "E-NOR",
            'document_ids': [
                (0, 0, {'document_type_id': cls.doc_inv.id, 'is_mandatory': True})]})

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@1610.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.ops_agent = user("Ops Agent E", 'operations')
        cls.ops_head = user("Ops Head E", 'ops_manager')
        cls.finance = user("Finance E", 'finance')
        cls.finance_head = user("Finance Head E", 'finance_manager')
        cls.holder = env['hr.employee'].create({
            'name': "Ops Agent E", 'user_id': cls.ops_agent.id})

    # -----------------------------------------------------------------
    def _file(self, service=None, **extra):
        vals = {
            'customs_regime': 'im4', 'bl_awb_ref': "MEDUE000577",
            'goods_description': "Lingots", 'cargo_value': 1000000.0,
            'package_count': 12, 'weight_kg': 800.0, 'not_containerised': True,
            'partner_id': self.client.id,
            'service_type_id': (service or self.service).id}
        vals.update(extra)
        file = self.env['logistics.file'].create(vals)
        file.state = 'in_progress'
        return file

    def _receive(self, file, code, when):
        line = file.document_ids.filtered(
            lambda d: d.document_type_id.code == code)
        self.assertTrue(line, code)
        line.write({'received': True, 'date_received': when})
        return line

    def _wizard(self, file, **vals):
        base = {'category_id': self.cat_port.id, 'description': "Ligne",
                'amount': 80000, 'journal_id': self.till.id}
        base.update(vals)
        return self.env['logistics.expense.capture.wizard'].with_user(
            self.ops_agent).with_context(active_id=file.id).create(base)

    def _paid(self, exp):
        exp = exp.with_env(self.env)
        exp.with_user(self.ops_head).action_approve()
        exp.with_user(self.finance).action_submit_settlement()
        exp.with_user(self.finance_head).action_approve_settlement()
        exp.action_settle()
        return exp

    # =================================================================
    def test_01_a_manifesting_vendor_asks_for_the_date_before_the_amount(self):
        file = self._file()
        wizard = self._wizard(file, vendor_id=self.terminal.id)
        self.assertFalse(wizard.needs_manifesting_date,
                         "an ordinary vendor asks for nothing")
        wizard.action_submit_close()
        wizard = self._wizard(file, vendor_id=self.line.id)
        self.assertTrue(wizard.needs_manifesting_date,
                        "a manifesting vendor reveals the date")
        with self.assertRaises(UserError) as caught:
            wizard.action_submit_close()
        self.assertIn("manifesting date", str(caught.exception))
        wizard.manifesting_date = "2026-10-03"
        wizard.action_submit_close()
        exp = file.expense_ids.filtered(lambda e: e.vendor_id == self.line)
        self.assertEqual(str(exp.manifesting_date), "2026-10-03")
        self.assertEqual(str(file.manifesting_date), "2026-10-03",
                         "the file reads it off the disbursement")
        # the dialog puts the vendor and the date BEFORE the amount
        arch = self.env['logistics.expense.capture.wizard'].with_user(
            self.ops_agent).get_view()['arch']
        self.assertLess(arch.index('name="vendor_id"'), arch.index('name="amount"'))
        self.assertLess(arch.index('name="manifesting_date"'),
                        arch.index('name="amount"'))

    def test_02_transit_time_for_import_maritime(self):
        file = self._file()
        self.assertFalse(file.transit_start)
        self._receive(file, 'INV', "2026-10-01 09:00:00")
        self.assertFalse(file.documents_received_on,
                         "one mandatory document is still missing")
        self._receive(file, 'E-OTH', "2026-10-02 10:00:00")
        self.assertEqual(str(file.documents_received_on), "2026-10-02 10:00:00")
        self.assertFalse(file.transit_start,
                         "'later' needs the manifesting date too")
        wizard = self._wizard(file, vendor_id=self.line.id,
                              manifesting_date="2026-10-05")
        wizard.action_submit_close()
        self.assertEqual(str(file.transit_start), "2026-10-05 00:00:00",
                         "the later of the two: the manifesting date")
        self.assertFalse(file.transit_end, "not paid yet")
        exp = file.expense_ids.filtered(lambda e: e.vendor_id == self.line)
        self._paid(exp)
        self.assertTrue(exp.date_settled)
        self.assertEqual(file.transit_end, exp.date_settled,
                         "ends when Finance paid the manifesting vendor")
        self.assertGreater(file.transit_days, 0)
        row = self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id), ('step', '=', 'file_transit')])
        self.assertEqual(len(row), 1, "one measured row in Reporting")
        self.assertTrue(row.is_done)
        self.assertAlmostEqual(row.days_taken, file.transit_days, places=1)
        target = self.env['clearance.turnaround.target'].search(
            [('step', '=', 'file_transit'),
             ('company_id', '=', self.env.company.id)], limit=1)
        self.assertTrue(target, "a target is seeded for the transit time")
        # a manifesting date later than the documents, but documents
        # later than manifesting on another file: the documents win
        other = self._file()
        self._wizard(other, vendor_id=self.line.id,
                     manifesting_date="2026-09-20").action_submit_close()
        self._receive(other, 'INV', "2026-10-01 09:00:00")
        self._receive(other, 'E-OTH', "2026-10-03 08:00:00")
        self.assertEqual(str(other.transit_start), "2026-10-03 08:00:00")

    def test_03_the_overall_turnaround_ends_on_the_delivery_date(self):
        file = self._file()
        self._receive(file, 'INV', "2026-10-01 09:00:00")
        self.assertEqual(str(file.commercial_invoice_received),
                         "2026-10-01 09:00:00")
        self.assertFalse(file.delivery_date)
        self.assertEqual(file.overall_turnaround_days, 0.0)
        # a transport advance to the requester
        wizard = self._wizard(file, category_id=self.cat_transport.id,
                              description="Livraison Edea", is_advance=True)
        wizard.action_submit_close()
        exp = file.expense_ids.filtered(lambda e: e.category_id == self.cat_transport)
        self.assertTrue(exp.needs_delivery_date)
        self._paid(exp)
        self.env['ir.attachment'].create({
            'name': "bon.pdf", 'res_model': 'logistics.expense',
            'res_id': exp.id, 'datas': b"UERG"})
        with self.assertRaises(UserError) as caught:
            exp.with_user(self.ops_agent).action_submit_justification()
        self.assertIn("Delivery Date", str(caught.exception))
        exp.with_user(self.ops_agent).delivery_date = "2026-10-12"
        exp.with_user(self.ops_agent).action_submit_justification()
        self.assertEqual(exp.state, 'justification_submitted')
        self.assertEqual(str(file.delivery_date), "2026-10-12")
        self.assertAlmostEqual(file.overall_turnaround_days, 10.6, places=1)
        row = self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id), ('step', '=', 'file_overall')])
        self.assertEqual(len(row), 1)
        self.assertTrue(row.is_done)
        self.assertAlmostEqual(row.days_taken, 10.625, places=2)
        self.assertTrue(self.env['clearance.turnaround.target'].search(
            [('step', '=', 'file_overall')], limit=1))

    def test_04_a_cost_that_is_not_transport_asks_for_no_delivery_date(self):
        file = self._file()
        wizard = self._wizard(file, description="Frais de ligne", is_advance=True)
        wizard.action_submit_close()
        exp = file.expense_ids
        self.assertFalse(exp.needs_delivery_date)
        self._paid(exp)
        self.env['ir.attachment'].create({
            'name': "recu.pdf", 'res_model': 'logistics.expense',
            'res_id': exp.id, 'datas': b"UERG"})
        exp.with_user(self.ops_agent).action_submit_justification()
        self.assertEqual(exp.state, 'justification_submitted')
        self.assertFalse(file.delivery_date)

    def test_05_the_rules_are_per_service_and_import_maritime_is_seeded(self):
        im = self.env['logistics.service.type'].with_context(
            active_test=False).search([('code', '=', 'IM')], limit=1)
        self.assertTrue(im, "the seeded Import Maritime service")
        self.assertEqual(im.transit_start_rule, 'later')
        self.assertEqual(im.transit_end_rule, 'vendor_paid')
        self.assertFalse(self.no_rule.transit_start_rule)
        file = self._file(service=self.no_rule)
        self._receive(file, 'INV', "2026-10-01 09:00:00")
        self.assertFalse(file.transit_start, "no rule, nothing measured")
        self.assertFalse(self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id), ('step', '=', 'file_transit')]))
        action = self.env.ref('elite_clearance.action_logistics_service_type_transit')
        self.assertEqual(action.res_model, 'logistics.service.type')
        self.assertTrue(self.env.ref('elite_clearance.menu_clearance_transit_settings'))
        # the settings page offers the manifesting vendors
        Wizard = self.env['clearance.settings.wizard']
        self.assertIn('clearance_manifesting_vendor_ids', Wizard._fields)
        self.assertIn('clearance_manifesting_vendor_ids',
                      Wizard.get_view()['arch'])
