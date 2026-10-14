"""Customer Service owns the customer record (owner, 14/10/2026).

The Billing Agent group used to imply Odoo's contact-creation group so
the billing screen could write the client's details back. The data
file no longer lists that implication, but an XML `(4, ref)` command
only ever ADDS a link: a database upgraded from an earlier build keeps
it, and Billing would still be able to edit customers. So the link is
removed here, through the ORM, which also takes the group off the
users who held it only through Billing.
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    billing = env.ref('elite_clearance.group_clearance_billing',
                      raise_if_not_found=False)
    contacts = env.ref('base.group_partner_manager', raise_if_not_found=False)
    if billing and contacts and contacts in billing.implied_ids:
        billing.write({'implied_ids': [(3, contacts.id)]})
