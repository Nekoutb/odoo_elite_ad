# Runs inside "odoo shell" on the STAGING copy: withdraws every module
# under Odoo's Enterprise licence through Odoo's own uninstall.
# GUARD: the Clearance application (elite_clearance, elite_clearance_teese)
# is LGPL-3 and must never be in the set, directly or as a dependent.
Module = env['ir.module.module']
env.cr.execute("SELECT count(*) FROM hr_payslip")
print("payslips on record:", env.cr.fetchone()[0])
before = Module.search([('license', '=like', 'OEEL%'), ('state', '=', 'installed')])
print("to uninstall:", len(before))
affected = set((before | before.downstream_dependencies()).mapped('name'))
protected = {'elite_clearance', 'elite_clearance_teese', 'account', 'hr', 'mail', 'analytic', 'base', 'l10n_cm', 'l10n_syscohada'}
clash = affected & protected
if clash:
    raise SystemExit("ABORT: these protected modules would be touched: %s" % sorted(clash))
print("clearance app protected: elite_clearance stays", Module.search([('name', '=', 'elite_clearance')]).state)
before.button_immediate_uninstall()
env.cr.commit()
left = env['ir.module.module'].search([('license', '=like', 'OEEL%'), ('state', '!=', 'uninstalled')])
print("still not uninstalled:", len(left), [(m.name, m.state) for m in left][:10])
print("after: elite_clearance", Module.search([('name', '=', 'elite_clearance')]).state,
      "/ elite_clearance_teese", Module.search([('name', '=', 'elite_clearance_teese')]).state)
