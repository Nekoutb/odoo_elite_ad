# -*- coding: utf-8 -*-
"""Legacy uploads (brief v3, 19/10/2026): the billing status, the round
and the freeze for files billed under the earlier builds.

`legacy_relief` is a stored compute, so the upgrade fills it from
date_opened by itself. What it cannot know is that a file carrying a
standing invoice was billed: that is round 1, locked, with its recharged
disbursements frozen. A file opened after the cutoff books its variance
at billing and has no débours result."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    File = env['logistics.file'].with_context(clearance_migration=True)
    files = File.search([('invoice_id', '!=', False)])
    for file in files:
        if not file.invoice_id.sudo()._clearance_stands():
            continue
        vals = {}
        if file.billing_status == 'not_billed':
            vals['billing_status'] = 'billed'
        if not file.billing_round:
            vals['billing_round'] = 1
        if vals:
            file.write(vals)
        billed = file.expense_ids.filtered(
            lambda e: e.billed_line_id and not e.is_frozen)
        billed.write({'is_frozen': True, 'billing_round': 1})
        file.invoice_ids.filtered(
            lambda m: not m.billing_round and m.move_type in (
                'out_invoice', 'out_refund')).write({'billing_round': 1})
    # no débours result for files opened after the cutoff
    cr.execute("""
        UPDATE logistics_file SET result_status = 'none'
         WHERE legacy_relief IS NOT TRUE AND result_status = 'not_billed'
    """)
