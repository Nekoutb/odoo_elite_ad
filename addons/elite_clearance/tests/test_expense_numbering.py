# -*- coding: utf-8 -*-
"""Disbursement references continue from the old system (owner,
20/10/2026): FA, the year, the month, then the running number of the
year - FA26051022 - and Settings takes the last legacy reference."""
import re

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..hooks import configure_expense_sequence


@tagged('post_install', '-at_install')
class TestExpenseNumbering(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        configure_expense_sequence(env)
        cls.company = env.company
        cls.vendor = env['res.partner'].create({
            'name': "Fournisseur N", 'is_company': True, 'supplier_rank': 1})
        cls.client = env['res.partner'].create({
            'name': "Client Numbering", 'is_company': True})
        cls.cat = env['logistics.expense.category'].create({
            'name': "KCT numbering", 'code': "N-KCT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Import numbering", 'code': "N-IM", 'commission_rate': 0.0})
        cls.file = env['logistics.file'].with_context(
            clearance_migration=True).create({
                'name': "2026NIM0001", 'partner_id': cls.client.id,
                'service_type_id': cls.service.id,
                'date_opened': "2026-09-01", 'not_containerised': True})
        cls.file.write({'state': 'in_progress'})
        today = fields.Date.context_today(cls.file)
        cls.yy, cls.mm = today.strftime('%y'), today.strftime('%m')

    def _expense(self):
        return self.env['logistics.expense'].with_context(
            legacy_import=True).create({
                'file_id': self.file.id, 'category_id': self.cat.id,
                'description': "numbering", 'amount': 1000,
                'vendor_id': self.vendor.id})

    def test_01_the_reference_reads_fa_year_month_number(self):
        sequence = self.env.ref('elite_clearance.seq_logistics_expense')
        self.assertEqual(sequence.prefix, 'FA%(y)s%(month)s')
        self.assertEqual(sequence.padding, 4)
        self.assertTrue(sequence.use_date_range)
        name = self._expense().name
        self.assertRegex(name, r'^FA%s%s\d{4}$' % (self.yy, self.mm))

    def test_02_numbering_continues_from_the_legacy_reference(self):
        self.company.clearance_legacy_last_expense_ref = "fa%s051022" % self.yy
        self.assertEqual(self.company.clearance_legacy_last_expense_ref,
                         "FA%s051022" % self.yy, "stored upper-case")
        self.assertEqual(self._expense().name, "FA%s%s1023" % (self.yy, self.mm),
                         "the number after the last one, this month")
        self.assertEqual(self._expense().name, "FA%s%s1024" % (self.yy, self.mm))
        with self.assertRaisesRegex(UserError, "already been keyed"):
            self.company.clearance_legacy_last_expense_ref = "FA%s050005" % self.yy
        with self.assertRaisesRegex(UserError, "not a disbursement reference"):
            self.company.clearance_legacy_last_expense_ref = "EXP/2026/00012"
        # moving it forward is allowed
        self.company.clearance_legacy_last_expense_ref = "FA%s091500" % self.yy
        self.assertEqual(self._expense().name, "FA%s%s1501" % (self.yy, self.mm))
        # another year's reference sets that year's series, not this one's
        last_year = "%02d" % ((int(self.yy) - 1) % 100)
        self.company.clearance_legacy_last_expense_ref = "FA%s120999" % last_year
        self.assertEqual(self._expense().name, "FA%s%s1502" % (self.yy, self.mm))
        sequence = self.env.ref('elite_clearance.seq_logistics_expense')
        ranges = {str(r.date_from)[:4]: r.number_next for r in sequence.date_range_ids}
        self.assertEqual(ranges.get("20" + last_year), 1000)
        self.assertTrue(re.fullmatch(r'\d{4}', "20" + last_year))
