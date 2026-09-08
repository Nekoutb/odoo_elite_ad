"""What an upgrade does not do by itself.

Two things, both of which would otherwise be silently missing on staging
and production while looking perfect on a fresh install:

1. `post_init_hook` runs on INSTALL only - odoo/modules/loading.py only
   calls it when the update operation is 'install'. The service catalogue
   is seeded and renamed by that hook, so without this the owner's four
   services never reach a database that already had the module.

2. `clearance_charged` is new, and the printed invoice now takes each
   disbursement row from it. Every line written before this version has
   nothing in it, so an invoice already issued would re-print its
   disbursements as zero. Backfilling it with what the line actually
   carries makes an old document print exactly as it printed before.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1. the catalogue: create-if-missing, rename what we named, retire BO
    from odoo.addons.elite_clearance.hooks import seed_clearance_master_data
    seed_clearance_master_data(env)

    # 2. an invoice issued before this version prints as it always did
    cr.execute("""
        UPDATE account_move_line
           SET clearance_charged = price_subtotal
         WHERE clearance_category = 'debours'
           AND COALESCE(clearance_charged, 0) = 0
    """)
