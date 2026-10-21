# -*- coding: utf-8 -*-
"""Owner, 21/10/2026: the customer's e-mail address is never a blocking
point; an incomplete customer record never stops a file from opening -
it stops the invoice, and the refusal carries the customer record."""
from odoo.exceptions import RedirectWarning, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec2110(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.client = env['res.partner'].create({
            'name': "Client Sans Courriel", 'is_company': True,
            'street': "BP 3 Douala", 'email': False,
            'vat': "M000000000333E", 'company_registry': "RC/DLA/2026/B/0333",
            'clearance_invoice_name': "CLIENT SANS COURRIEL SA"})
        cls.bare = env['res.partner'].create({
            'name': "Client Nu", 'is_company': True})
        cls.service = env['logistics.service.type'].create({
            'name': "Import sans courriel", 'code': "E-IM", 'commission_rate': 0.0})
        cls.port = env['logistics.port'].create({'name': "Douala E"})

    def _file(self, partner):
        return self.env['logistics.file'].with_context(skip_checklist=True).create({
            'partner_id': partner.id, 'service_type_id': self.service.id,
            'customs_regime': 'im4', 'bl_awb_ref': "BL-E-%s" % partner.id,
            'goods_description': "Marchandises", 'cargo_value': 1000.0,
            'package_count': 1, 'weight_kg': 10.0, 'not_containerised': True,
            'shipment_type': 'conventional', 'importer_name': "Importateur",
            'port_id': self.port.id,
            'incoterm_id': self.env.ref('account.incoterm_CIF').id,
            'cargo_value_currency_id': self.env.company.currency_id.id})

    def test_01_no_email_blocks_neither_the_opening_nor_the_bill(self):
        file = self._file(self.client)
        self.assertFalse(self.client.email)
        self.assertNotIn('email', [name for name, _label in file.CLIENT_ESSENTIALS])
        self.assertFalse(file.client_missing_details,
                         "the banner lists nothing: the e-mail is not essential")
        file._check_ready_to_work()
        file._check_client_billable()
        # the record is still incomplete without its NIU
        self.client.vat = False
        self.assertIn("NIU", file.client_missing_details)

    def test_02_an_incomplete_record_opens_the_file_and_blocks_the_invoice(self):
        file = self._file(self.bare)
        self.assertIn("full name", file.client_missing_details)
        file._check_ready_to_work()             # the opening is not blocked
        file.action_start_work()
        self.assertEqual(file.state, 'in_progress')
        self.assertTrue(file.client_missing_details, "the banner stays up")
        with self.assertRaises(RedirectWarning) as caught:
            file._check_client_billable()
        self.assertIsInstance(caught.exception, UserError)
        message, action, button = caught.exception.args[:3]
        self.assertIn("Tax ID (NIU)", message)
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(action['res_id'], self.bare.id,
                         "the refusal opens the customer record")
        self.assertEqual(button, "Open the Customer Record")
        self.assertEqual(file.action_open_customer_record()['res_id'], self.bare.id)
        # completed, the bill goes through the gate
        self.bare.write({
            'clearance_invoice_name': "CLIENT NU SA", 'street': "BP 4 Douala",
            'vat': "M000000000444N", 'company_registry': "RC/DLA/2026/B/0444"})
        self.assertFalse(file.client_missing_details)
        file._check_client_billable()
