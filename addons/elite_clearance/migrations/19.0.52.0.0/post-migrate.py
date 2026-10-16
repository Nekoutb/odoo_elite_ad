"""Transit time rules (owner, 16/10/2026).

Import Maritime measures from the later of the manifesting date and the
day every opening document was in, to the day Finance paid the
manifesting vendor. The hook seeds it on a fresh database; an upgraded
one gets it here, and only where no rule has been set.
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.elite_clearance.hooks import seed_transit_rules
    seed_transit_rules(env)
