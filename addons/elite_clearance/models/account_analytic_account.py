from odoo import api, models


class AccountAnalyticAccount(models.Model):
    """Clearance analytic accounts name themselves and nothing else.

    Odoo composes an analytic account's label as `[code] name - client`,
    which for a clearance file printed the file number twice — once in the
    brackets and once in the name — and then spelled the client out in full,
    so no two tags were the same width. A clearance account's `name` is
    already exactly what should be read (`2026AI0072 - CTC`), so it is used
    verbatim. The `code` is still stored, and still searchable; it is simply
    not repeated on screen.
    """

    _inherit = 'account.analytic.account'

    @api.depends('name', 'code', 'partner_id', 'plan_id')
    def _compute_display_name(self):
        plan = self.env.ref('elite_clearance.analytic_plan_clearance',
                            raise_if_not_found=False)
        ours = self.filtered(lambda a: a.plan_id == plan) if plan else self.browse()
        others = self - ours
        if others:
            super(AccountAnalyticAccount, others)._compute_display_name()
        for account in ours:
            account.display_name = account.name
