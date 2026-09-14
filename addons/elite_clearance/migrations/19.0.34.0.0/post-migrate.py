"""Point every company at the undisclosed numbering, and classify the
expense categories that cannot be justified.

The sequences ship as data but a company has to name them, and an upgrade
never runs the post-install hook.

Every expense category keeps the default it already has, Justifiable.
Which of them can never be justified is the owner's call, ticked under
Clearance -> Configuration -> Expense Categories - guessing it here would
change how those costs POST, quietly, on somebody else's judgement.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    sequences = (
        ('clearance_undisclosed_file_sequence_id',
         'elite_clearance.seq_clearance_undisclosed_file'),
        ('clearance_undisclosed_invoice_sequence_id',
         'elite_clearance.seq_clearance_undisclosed_invoice'),
    )
    pointed = 0
    for company in env['res.company'].sudo().search([]):
        for field, xmlid in sequences:
            if company[field]:
                continue
            sequence = env.ref(xmlid, raise_if_not_found=False)
            if sequence:
                company[field] = sequence.id
                pointed += 1

    _logger.info(
        "19.0.34.0.0: %s undisclosed sequence(s) named.", pointed)
