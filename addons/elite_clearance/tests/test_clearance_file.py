from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestClearanceFile(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = cls.env['res.partner'].create({
            'name': "Test Importer SARL", 'is_company': True,
        })
        cls.doc_bl = cls.env['logistics.document.type'].create({
            'name': "Bill of Lading", 'code': "T-BL",
        })
        cls.doc_coo = cls.env['logistics.document.type'].create({
            'name': "Certificate of Origin", 'code': "T-COO",
        })
        cls.service = cls.env['logistics.service.type'].create({
            'name': "Test import clearance",
            'code': "T-IMP",
            'document_ids': [
                (0, 0, {'document_type_id': cls.doc_bl.id, 'is_mandatory': True}),
                (0, 0, {'document_type_id': cls.doc_coo.id, 'is_mandatory': False}),
            ],
        })

    def _new_file(self):
        return self.env['logistics.file'].create({
            'partner_id': self.client.id,
            'service_type_id': self.service.id,
        })

    def test_01_reference_and_checklist(self):
        """A new file gets a sequence reference and the service checklist."""
        file = self._new_file()
        self.assertNotEqual(file.name, "New", "The sequence did not fire.")
        year = fields.Date.context_today(file).strftime("%Y")
        self.assertTrue(
            file.name.startswith(year + self.service.code.upper()),
            "Reference %s should be <year><type code><number>." % file.name)
        self.assertTrue(file.name.endswith("0001") or file.name[-4:].isdigit())
        self.assertEqual(len(file.document_ids), 2)
        self.assertEqual(file.missing_mandatory_count, 1)
        self.assertFalse(file.documents_complete)

    def test_02_analytic_account_created(self):
        """Every file carries its own analytic account from creation."""
        file = self._new_file()
        self.assertTrue(file.analytic_account_id)
        self.assertEqual(file.analytic_account_id.name, file.name)
        self.assertEqual(file.analytic_account_id.partner_id, self.client)

    def test_03_cannot_start_without_documents(self):
        """The gate holds: no work while a mandatory document is missing."""
        file = self._new_file()
        with self.assertRaises(UserError):
            file.action_start_work()
        self.assertEqual(file.state, 'draft')

    def test_04_start_once_documents_received(self):
        """Ticking the mandatory document opens the gate."""
        file = self._new_file()
        file.document_ids.filtered('is_mandatory').received = True
        self.assertTrue(file.documents_complete)
        file.action_start_work()
        self.assertEqual(file.state, 'in_progress')

    def test_05_waiver_path(self):
        """An approved waiver opens the gate with documents still missing."""
        file = self._new_file()
        with self.assertRaises(UserError):
            file.action_request_waiver()  # no justification yet
        file.waiver_reason = "BL expected from the shipping line on Friday."
        file.action_request_waiver()
        self.assertEqual(file.waiver_state, 'requested')
        file.action_approve_waiver()
        self.assertEqual(file.waiver_state, 'approved')
        self.assertTrue(file.can_start)
        file.action_start_work()
        self.assertEqual(file.state, 'in_progress')
        self.assertFalse(file.documents_complete, "Documents are still missing.")

    def test_06_non_manager_cannot_approve(self):
        """A plain clearance user cannot approve their own waiver."""
        user = self.env['res.users'].create({
            'name': "Ops Agent",
            'login': "ops.agent@test.example",
            'group_ids': [(6, 0, [
                self.env.ref('elite_clearance.group_clearance_user').id,
            ])],
        })
        file = self._new_file()
        file.waiver_reason = "Client sending the invoice tomorrow."
        file.action_request_waiver()
        with self.assertRaises(UserError):
            file.with_user(user).action_approve_waiver()

    def test_07_plain_user_can_open_a_file(self):
        """Regression: a clearance User — not a manager, not an accountant —
        must be able to create a file, which silently creates an analytic
        account behind the scenes.
        """
        user = self.env['res.users'].create({
            'name': "Ops Agent 2",
            'login': "ops.agent2@test.example",
            'group_ids': [(6, 0, [
                self.env.ref('elite_clearance.group_clearance_user').id,
            ])],
        })
        file = self.env['logistics.file'].with_user(user).create({
            'partner_id': self.client.id,
            'service_type_id': self.service.id,
        })
        self.assertTrue(file.analytic_account_id, "Analytic account not created.")
        self.assertTrue(file.document_ids, "Checklist not generated.")
        self.assertNotEqual(file.name, "New")


    def test_08_receiving_stamps_datetime(self):
        """Ticking a document as received stamps date AND time automatically,
        on every write path, and unticking clears it."""
        file = self._new_file()
        line = file.document_ids.filtered('is_mandatory')[:1]
        line.write({'received': True})          # plain write — no onchange
        self.assertTrue(line.date_received, "No timestamp was stamped.")
        stamped = line.date_received
        line.write({'received': True})          # writing again must not move it
        self.assertEqual(line.date_received, stamped)
        line.write({'received': False})
        self.assertFalse(line.date_received, "Unticking should clear the stamp.")

    def test_09_bulk_date_wizard(self):
        """The wizard applies one date/time to every selected line."""
        file = self._new_file()
        file.document_ids.write({'received': True})
        when = fields.Datetime.now().replace(microsecond=0)
        wiz = self.env['logistics.file.document.date.wizard'].with_context(
            active_id=file.id).create({'date_received': when})
        self.assertEqual(wiz.line_ids, file.document_ids,
                         "Received lines should be preselected.")
        wiz.action_apply()
        for line in file.document_ids:
            self.assertEqual(line.date_received, when)


    def test_10_batch_ticks_share_one_timestamp(self):
        """Lines received in the same save carry the identical timestamp."""
        file = self._new_file()
        file.document_ids.write({'received': True})
        stamps = set(file.document_ids.mapped('date_received'))
        self.assertEqual(len(stamps), 1,
                         "All lines ticked together must share one timestamp.")
