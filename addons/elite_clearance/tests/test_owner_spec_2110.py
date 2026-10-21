# -*- coding: utf-8 -*-
"""Owner, 21/10/2026: the customer's e-mail address is never a blocking
point - not at the opening of a file, not at billing."""
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
        cls.service = env['logistics.service.type'].create({
            'name': "Import sans courriel", 'code': "E-IM", 'commission_rate': 0.0})
        cls.file = env['logistics.file'].with_context(skip_checklist=True).create({
            'partner_id': cls.client.id, 'service_type_id': cls.service.id,
            'customs_regime': 'im4', 'bl_awb_ref': "BL-E1",
            'goods_description': "Marchandises", 'cargo_value': 1000.0,
            'package_count': 1, 'weight_kg': 10.0, 'not_containerised': True,
            'shipment_type': 'conventional', 'importer_name': "Importateur",
            'cargo_value_currency_id': env.company.currency_id.id})

    def test_01_no_email_blocks_neither_the_opening_nor_the_bill(self):
        self.assertFalse(self.client.email)
        self.assertNotIn('email', [name for name, _label in self.file.CLIENT_ESSENTIALS])
        self.assertFalse(self.file.client_missing_details,
                         "the banner lists nothing: the e-mail is not essential")
        self.file._check_client_complete()      # the opening gate
        self.file._check_client_billable()      # the billing gate
        # the record is still incomplete without its NIU
        self.client.vat = False
        self.assertIn("NIU", self.file.client_missing_details)
