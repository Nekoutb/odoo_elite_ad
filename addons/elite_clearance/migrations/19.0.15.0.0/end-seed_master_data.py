from odoo.addons.elite_clearance.hooks import seed_clearance_master_data


def migrate(cr, version):
    """Re-run the idempotent master-data seed after every upgrade, so a
    database that predates a new service type or expense category picks it
    up without anyone keying it by hand."""
    from odoo.api import Environment, SUPERUSER_ID
    env = Environment(cr, SUPERUSER_ID, {})
    seed_clearance_master_data(env)
