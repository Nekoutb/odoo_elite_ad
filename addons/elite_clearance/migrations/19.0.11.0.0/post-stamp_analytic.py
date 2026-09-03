def migrate(cr, version):
    """Back-stamp the file number on moves posted before the rule existed.

    Only lines with no distribution at all are touched, and only on moves
    that already name a clearance file, so nothing anyone chose by hand is
    overwritten.
    """
    from odoo.api import Environment, SUPERUSER_ID
    env = Environment(cr, SUPERUSER_ID, {})
    moves = env['account.move'].search([('logistics_file_id', '!=', False)])
    for move in moves:
        move._clearance_stamp_analytic()
