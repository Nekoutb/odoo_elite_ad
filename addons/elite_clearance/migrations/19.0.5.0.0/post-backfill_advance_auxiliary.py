def migrate(cr, version):
    """Give every existing staff member the auxiliary their advances need.

    Advances are carried on 421101 against the employee's work contact. hr
    creates that contact only as a side effect of writing a work e-mail or
    phone, so employees keyed before this version can have none — and an
    advance settled against them would have had nowhere to post. Backfill
    before anyone tries.
    """
    from odoo.api import Environment, SUPERUSER_ID
    env = Environment(cr, SUPERUSER_ID, {})
    employees = env['hr.employee'].with_context(active_test=False).search(
        [('work_contact_id', '=', False)])
    for employee in employees:
        employee._clearance_auxiliary_partner()
