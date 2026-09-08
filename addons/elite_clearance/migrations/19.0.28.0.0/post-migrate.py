"""Corrections that an ordinary upgrade cannot deliver.

1. The seeded master data now includes the PORTS. Port is required when
   a file is opened and offers no "create" entry, so a database with no
   ports cannot open a file at all - and `post_init_hook` runs on
   install only, so seeding has to be asked for here.

2. The record rules that hide a draft file live in a `noupdate="1"`
   block. That is right - an owner may tune them - but it also means a
   correction to the domain never reaches a database that already has
   the record. The domain is rewritten here to the corrected one, which
   also lets the file's Responsible see it, not only its author.

3. `clearance_charged` became `clearance_adjustment` (the difference
   rather than the absolute figure, so that correcting an invoice line
   moves the printed row with it). The old column is dropped; the new
   one defaults to zero, which already means "charged at cost".
"""

from odoo import SUPERUSER_ID, api

FILE_DRAFT = ("['|', ('state', '!=', 'draft'), "
              "'|', ('create_uid', '=', user.id), ('user_id', '=', user.id)]")
DOC_DRAFT = ("['|', ('file_id.state', '!=', 'draft'), "
             "'|', ('file_id.create_uid', '=', user.id), "
             "('file_id.user_id', '=', user.id)]")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    from odoo.addons.elite_clearance.hooks import seed_clearance_master_data
    seed_clearance_master_data(env)

    for xmlid, domain in (
            ('elite_clearance.rule_logistics_file_draft_is_the_authors',
             FILE_DRAFT),
            ('elite_clearance.rule_logistics_file_document_draft', DOC_DRAFT)):
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.domain_force = domain

    cr.execute("""
        ALTER TABLE account_move_line DROP COLUMN IF EXISTS clearance_charged
    """)
