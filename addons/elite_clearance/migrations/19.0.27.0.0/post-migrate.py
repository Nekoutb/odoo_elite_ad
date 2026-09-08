"""What an upgrade does not do by itself.

`post_init_hook` runs on INSTALL only - odoo/modules/loading.py calls it
only when the update operation is 'install'. The service catalogue and
the rest of the master data are seeded by that hook, so without this they
would reach a fresh CI database and never staging or production.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.elite_clearance.hooks import seed_clearance_master_data
    seed_clearance_master_data(env)
