from odoo.addons.elite_clearance.hooks import seed_clearance_master_data


def migrate(cr, version):
    from odoo.api import Environment, SUPERUSER_ID
    env = Environment(cr, SUPERUSER_ID, {})
    seed_clearance_master_data(env)
