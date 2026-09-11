from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExpenseDocuments(TransactionCase):
    """The receipts behind an expense, as the capture dialog handles them.

    A file dropped on the dialog is uploaded by the browser against the
    model with no record yet (res_id 0), then linked through
    `attachment_ids`. Everything below is what the server must do with
    that link - as the restricted user who dropped it, never as admin.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.client = env['res.partner'].create({
            'name': "Documents Client", 'is_company': True,
            'street': "BP 1234 Douala", 'email': "client@test.cm",
            'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001", 'clearance_invoice_name': "Full Legal Name SARL"})
        cls.vendor = env['res.partner'].create({
            'name': "Douala Terminal", 'is_company': True})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port", 'code': "T-DOC"})
        cls.service = env['logistics.service.type'].create({
            'name': "Documents test", 'code': "T-DOC"})
        cls.file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW000009",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'
        cls.ops = env['res.users'].create({
            'name': "Ops Documents", 'login': "ops.documents@doc.test",
            'group_ids': [(6, 0, [env.ref(
                'elite_clearance.group_clearance_operations').id])]})

    def _dropped(self, name="receipt.pdf"):
        """What /web/binary/upload_attachment creates for a record that
        does not exist yet."""
        return self.env['ir.attachment'].with_user(self.ops).create({
            'name': name, 'raw': b"%PDF-1.4 receipt",
            'res_model': 'logistics.expense', 'res_id': 0})

    def _vals(self, **extra):
        vals = {
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Terminal handling", 'amount': 25000}
        vals.update(extra)
        return vals

    def test_01_a_receipt_dropped_on_a_new_expense_is_adopted_by_it(self):
        att = self._dropped()
        exp = self.env['logistics.expense'].with_user(self.ops).create(
            self._vals(vendor_id=self.vendor.id,
                       attachment_ids=[Command.link(att.id)]))
        self.assertEqual(att.res_model, 'logistics.expense')
        self.assertEqual(att.res_id, exp.id,
                         "the link points the upload at the expense")
        self.assertIn(att, exp.attachment_ids)
        self.assertTrue(exp.date_documents_submitted,
                        "the first document dates its own arrival")
        self.assertEqual(exp.vendor_id, self.vendor,
                         "the originator names who is paid")
        self.assertEqual(exp.unit_label, "Par dossier",
                         "the unit is fixed, not asked for")
        # and the justification count sees it, like a chatter upload
        self.assertEqual(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'logistics.expense'),
            ('res_id', '=', exp.id)]), 1)

    def test_02_the_field_shows_the_chatter_uploads_and_removal_deletes(self):
        exp = self.env['logistics.expense'].with_user(self.ops).create(
            self._vals())
        chatter = self.env['ir.attachment'].with_user(self.ops).create({
            'name': "ticket.png", 'raw': b"png", 'res_model': exp._name,
            'res_id': exp.id})
        self.assertIn(chatter, exp.attachment_ids,
                      "one set of documents, whichever way they arrived")
        exp.with_user(self.ops).write(
            {'attachment_ids': [Command.unlink(chatter.id)]})
        self.assertFalse(chatter.exists(),
                         "taken off the dialog means deleted, not orphaned")
        self.assertFalse(exp.attachment_ids)

    def test_03_an_existing_expense_takes_a_dropped_file(self):
        exp = self.env['logistics.expense'].with_user(self.ops).create(
            self._vals())
        self.assertFalse(exp.date_documents_submitted)
        att = self._dropped("invoice.pdf")
        exp.with_user(self.ops).write(
            {'attachment_ids': [Command.link(att.id)]})
        self.assertEqual(att.res_id, exp.id)
        self.assertEqual(exp.attachment_ids, att)
        self.assertTrue(exp.date_documents_submitted)
        stamp = exp.date_documents_submitted
        exp.with_user(self.ops).write(
            {'attachment_ids': [Command.link(self._dropped("second.pdf").id)]})
        self.assertEqual(exp.date_documents_submitted, stamp,
                         "the stamp is the FIRST document's, once")
        self.assertEqual(len(exp.attachment_ids), 2)
