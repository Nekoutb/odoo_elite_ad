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
            'customs_regime': 'im4',
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
        """Every file carries its own analytic account from creation, and its
        tag reads the file number ONCE followed by the client's slug."""
        file = self._new_file()
        analytic = file.analytic_account_id
        self.assertTrue(analytic)
        self.assertEqual(analytic.partner_id, self.client)
        slug = self.client.clearance_slug
        self.assertEqual(len(slug or ''), 3, "the slug is always three letters")
        self.assertEqual(analytic.name, "%s - %s" % (file.name, slug))
        self.assertEqual(analytic.code, file.name)
        # the label the user sees: no brackets, no repeat, no full client name
        self.assertEqual(analytic.display_name, "%s - %s" % (file.name, slug))
        self.assertNotIn("[", analytic.display_name)
        self.assertEqual(analytic.display_name.count(file.name), 1)
        self.assertNotIn(self.client.name, analytic.display_name)

    def test_02b_the_slug_is_generated_once_and_kept(self):
        """Three letters per client, assigned at the first file and stable
        for every file after it."""
        first = self._new_file()
        slug = self.client.clearance_slug
        self.assertTrue(slug)
        second = self._new_file()
        self.assertEqual(self.client.clearance_slug, slug, "never regenerated")
        self.assertTrue(second.analytic_account_id.name.endswith(" - " + slug))
        self.assertEqual(first.partner_slug, slug)

    def test_02c_slug_rules_and_collisions(self):
        """Initials for a long name, opening letters for a short one, and
        never the same three letters for two different clients."""
        Partner = self.env['res.partner']
        cases = {
            "PIZZAROTI": "PIZ",                # one word -> opening letters
            "CTC": "CTC",
            "AB": "ABX",                       # padded to three
            "CTC SA": "CTC",                   # SA is noise
            "Élimelec Sarl": "ELI",            # accents folded, SARL dropped
            "SOCIETE DES BOISSONS DU CAMEROUN": "BOI",   # two telling words
            # three telling words -> initials
            "Societe Nationale des Hydrocarbures du Cameroun": "NHC",
        }
        for name, expected in cases.items():
            candidate = Partner.new({'name': name})._clearance_slug_candidate()
            self.assertEqual(candidate, expected, "%s -> %s" % (name, candidate))

        # two clients that want the same three letters get different ones
        a = Partner.create({'name': "Pizzaroti Cameroun", 'is_company': True})
        b = Partner.create({'name': "Pizzaroti Douala", 'is_company': True})
        slug_a = a._clearance_ensure_slug()
        slug_b = b._clearance_ensure_slug()
        self.assertEqual(len(slug_a), 3)
        self.assertEqual(len(slug_b), 3)
        self.assertNotEqual(slug_a, slug_b, "slugs must identify one client")

    def test_02d_a_non_clearance_analytic_account_is_untouched(self):
        """The override applies to the Clearance plan only; Odoo's own
        labelling elsewhere is left exactly as it was."""
        plan = self.env['account.analytic.plan'].create({'name': "Other"})
        other = self.env['account.analytic.account'].create({
            'name': "Something", 'code': "SMT", 'plan_id': plan.id,
            'partner_id': self.client.id})
        self.assertEqual(
            other.display_name,
            "[SMT] Something - %s" % self.client.name,
            "core behaviour must survive outside the Clearance plan")

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
            'customs_regime': 'im4',
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

    def test_11_refusing_needs_a_pending_request(self):
        """Refuse is an answer to a request, not a state you can jump to."""
        file = self._new_file()
        with self.assertRaises(UserError):
            file.action_refuse_waiver()
        self.assertEqual(file.waiver_state, 'none')

    def test_12_draft_file_stays_the_authors_to_discard(self):
        """The cancel guard must not lock a plain user out of throwing away
        a draft they just opened by mistake."""
        user = self.env['res.users'].create({
            'name': "Ops Agent 3",
            'login': "ops.agent3@test.example",
            'group_ids': [(6, 0, [
                self.env.ref('elite_clearance.group_clearance_user').id,
            ])],
        })
        file = self.env['logistics.file'].with_user(user).create({
            'customs_regime': 'im4',
            'partner_id': self.client.id,
            'service_type_id': self.service.id,
        })
        file.with_user(user).action_cancel()
        self.assertEqual(file.state, 'cancel')
