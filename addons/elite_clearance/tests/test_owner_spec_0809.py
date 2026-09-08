from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec0809(TransactionCase):
    """The owner's instructions of 08/09/2026, one test per instruction."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.client = env['res.partner'].create({
            'name': "Spec Client", 'is_company': True,
            'street': "BP 1234 Douala", 'email': "client@test.cm",
            'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001"})
        cls.service = env['logistics.service.type'].create({
            'name': "Spec service", 'code': "T-SPEC"})

        def user(name, group):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@spec.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.author = user("Spec Author", 'operations')
        cls.other = user("Spec Other", 'finance')
        cls.manager = user("Spec Manager", 'manager')

    def _file(self, user=None, **extra):
        vals = {
            'customs_regime': 'im4', 'partner_id': self.client.id,
            'service_type_id': self.service.id,
            'bl_awb_ref': "MEDUW000100",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
        }
        vals.update(extra)
        model = self.env['logistics.file']
        if user:
            model = model.with_user(user)
        return model.create(vals)

    def _form_arch(self, user=None):
        model = self.env['logistics.file']
        if user:
            model = model.with_user(user)
        view = self.env.ref('elite_clearance.logistics_file_view_form')
        return etree.fromstring(model.get_view(view.id)['arch'])

    # -- 1. turnaround targets are hours, and may be fractional ---------
    def test_01_targets_are_fractional_hours(self):
        Target = self.env['clearance.turnaround.target']
        target = Target.search([('step', '=', 'file_start')], limit=1)
        self.assertTrue(target, "a target is seeded for every step")
        self.assertEqual(target.target_hours, 48.0, "two days, in hours")
        target.target_hours = 0.5              # thirty minutes
        self.assertEqual(target.target_hours, 0.5)
        self.assertNotIn('target_days', Target._fields,
                         "days are gone; the allowance is hours")
        self.assertEqual(
            self.env['clearance.turnaround']._fields['target_hours'].type,
            'float', "the view reports the same unit")

    # -- 2. four services, and only four -------------------------------
    def test_02_the_catalogue_is_the_four_services_sold(self):
        Service = self.env['logistics.service.type']
        seeded = Service.search([('code', 'in', ('IM', 'ES', 'AI', 'TR'))])
        self.assertEqual(
            sorted(seeded.mapped('name')),
            ["Aérien (Air Freight)", "Export", "Import Maritime", "Transport"])
        retired = Service.with_context(active_test=False).search(
            [('code', '=', 'BO')])
        self.assertTrue(all(not s.active for s in retired),
                        "Export Bois is retired, not deleted: files point at it")
        self.assertFalse(Service.search([('code', '=', 'BO')]),
                         "and it is off the list a biller picks from")

    # -- 3 + 5. cargo is keyed at creation; a container is optional -----
    def test_03_every_cargo_and_routing_field_is_asked_for(self):
        arch = self._form_arch()
        cargo = arch.xpath("//group[@name='cargo']//field")
        asked = {node.get('name'): node.get('required') for node in cargo}
        for name in ('port_id', 'employee_id', 'shipment_type', 'incoterm_id',
                     'customs_regime', 'package_count', 'weight_kg',
                     'cargo_value', 'cargo_value_currency_id',
                     'importer_name'):
            self.assertEqual(asked.get(name), "state in ('draft', 'in_progress')",
                             "%s must be keyed when the file is opened" % name)
        for name in ('container_count', 'container_type'):
            self.assertEqual(
                asked.get(name),
                "not not_containerised and state in ('draft', 'in_progress')",
                "%s is asked for only when there IS a container" % name)

    def test_05_cargo_that_is_not_in_a_container_says_so(self):
        file = self._file(container_count=2, container_type="40HC")
        arch = self._form_arch()
        for name in ('container_count', 'container_type'):
            node = arch.xpath("//group[@name='cargo']//field[@name='%s']" % name)[0]
            self.assertEqual(node.get('readonly'), "not_containerised")
            self.assertEqual(node.get('force_save'), "1",
                             "a readonly value is dropped on save without it")
        file.not_containerised = True
        file._onchange_not_containerised()
        self.assertEqual(file.container_count, 0)
        self.assertFalse(file.container_type,
                         "no container, so no count and no type to print")

    # -- 4. documents are dropped on the area they belong to ------------
    def test_04_the_checklist_area_takes_a_dropped_document(self):
        arch = self._form_arch()
        area = arch.xpath("//div[@class='o_clearance_documents_area']")
        self.assertTrue(area, "the checklist sits in a drop area")
        self.assertTrue(area[0].xpath(".//field[@name='document_ids']"),
                        "the checklist itself is inside it")
        field = area[0].xpath(".//field[@name='attachment_ids']")[0]
        self.assertEqual(field.get('widget'), "clearance_documents")
        self.assertIn("o_clearance_documents_area", field.get('options'))

        # and the server side: a file dropped before the record existed is
        # uploaded against the model with res_id 0, then linked
        dropped = self.env['ir.attachment'].with_user(self.author).create({
            'name': "bill-of-lading.pdf", 'raw': b"%PDF-1.4",
            'res_model': 'logistics.file', 'res_id': 0})
        file = self._file(user=self.author,
                          attachment_ids=[Command.link(dropped.id)])
        self.assertEqual(dropped.res_id, file.id)
        self.assertEqual(file.attachment_ids, dropped)
        # the expense dialog keeps its own dialog-wide drop zone
        capture = self.env.ref(
            'elite_clearance.logistics_expense_view_capture_form').arch
        self.assertIn('widget="clearance_documents"', capture)

    # -- 6. a draft file is its author's until work starts --------------
    def test_06_a_draft_file_is_not_yet_anybody_elses(self):
        file = self._file(user=self.author)
        self.assertEqual(file.state, 'draft')
        self.assertEqual(file.create_uid, self.author)

        self.assertTrue(file.with_user(self.author).read(['name']),
                        "its author sees it")
        self.assertTrue(file.with_user(self.manager).read(['name']),
                        "a manager can find a file left behind")
        self.assertFalse(
            self.env['logistics.file'].with_user(self.other).search(
                [('id', '=', file.id)]),
            "Finance does not see a file whose work has not started")
        with self.assertRaises(AccessError):
            file.with_user(self.other).read(['name'])

        file.with_user(self.author).action_start_work()
        self.assertEqual(file.state, 'in_progress')
        self.assertTrue(
            self.env['logistics.file'].with_user(self.other).search(
                [('id', '=', file.id)]),
            "once work has started it belongs to everyone who works it")
        self.assertTrue(file.with_user(self.other).read(['name']))
