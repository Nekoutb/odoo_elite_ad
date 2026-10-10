"""Every clearance team sees every file (owner, 10/10/2026).

The 08/09/2026 rules kept a draft file to its author until work started.
They live in a noupdate data file, so removing them from the XML does
not remove them from a database that already has them: Odoo's
_process_end only deletes records whose noupdate flag is off. Left in
place they would be harmless - rules in a group OR together and the new
rule reads everything - but a rule that says one thing next to a rule
that says the opposite is a trap for whoever reads the list next.
"""

from odoo import SUPERUSER_ID, api


RETIRED = (
    'elite_clearance.rule_logistics_file_draft_is_the_authors',
    'elite_clearance.rule_logistics_file_document_draft',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in RETIRED:
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.unlink()
