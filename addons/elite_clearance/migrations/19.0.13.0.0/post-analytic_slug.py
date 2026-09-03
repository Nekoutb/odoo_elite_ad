def migrate(cr, version):
    """Give every client with a file its three letters, and rename the
    analytic accounts that were reading the file number twice.

    Only accounts still carrying the old `name == code` shape are renamed,
    so an account somebody has renamed by hand is left alone.
    """
    from odoo.api import Environment, SUPERUSER_ID
    env = Environment(cr, SUPERUSER_ID, {})
    files = env['logistics.file'].with_context(active_test=False).search([])
    for partner in files.mapped('partner_id'):
        partner._clearance_ensure_slug()
    renamed = 0
    for file in files.filtered('analytic_account_id'):
        analytic = file.analytic_account_id
        if analytic.name != file.name:
            continue        # already named something deliberate
        slug = file.partner_id.commercial_partner_id.clearance_slug
        if not slug:
            continue
        analytic.write({'name': "%s - %s" % (file.name, slug),
                        'code': file.name})
        renamed += 1
    if renamed:
        env['ir.logging'].sudo().create({
            'name': 'elite_clearance.migration',
            'type': 'server',
            'level': 'INFO',
            'dbname': cr.dbname,
            'message': 'renamed %d clearance analytic accounts to '
                       '"<file> - <slug>"' % renamed,
            'path': 'migrations/19.0.13.0.0/post-analytic_slug.py',
            'func': 'migrate',
            'line': '1',
        })
