"""The accounting app reads "Finance" (owner, 11/10/2026).

The data record sets the English label when the module updates; this
writes the same word into every other active language, French included,
because a translated field keeps its other languages when the source
changes.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.elite_clearance.hooks import rename_finance_menu


def migrate(cr, version):
    rename_finance_menu(api.Environment(cr, SUPERUSER_ID, {}))
