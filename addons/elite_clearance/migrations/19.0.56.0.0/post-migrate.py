# -*- coding: utf-8 -*-
"""Handling due to the customer and the disbursement series (owner,
20/10/2026).

The hook seeds the Handling component and reshapes the disbursement
sequence on a fresh database; an upgraded one gets both here. The
sequence record is noupdate, so the data file never reaches it.
`is_handling` is no longer computed from the description: a flag an
earlier build set stays, nothing new is read off a label."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.elite_clearance.hooks import (
        configure_expense_sequence, seed_handling_service)
    seed_handling_service(env)
    configure_expense_sequence(env)
