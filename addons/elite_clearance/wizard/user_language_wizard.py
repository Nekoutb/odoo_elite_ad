"""The Clearance Administrator sets each user's language.

The application is bilingual (owner, 14/10/2026): English source, a
French translation shipped in `i18n/fr.po`. Odoo reads a user's
language off `res.users.lang`, and writing another user's record is
the Administration -> Access Rights group's privilege - which the
Clearance Administrator deliberately is not (07/10/2026). So this
screen lists the clearance users with their language, and `action_apply`
writes the language under sudo AFTER checking the caller holds the
Clearance Administrator group, the way the settings page does for the
General Manager. A language that is not yet active is activated through
Odoo's own installer, which also loads every module's translations for
it, so Odoo itself reads in that language too.
"""

from odoo import api, fields, models
from odoo.exceptions import AccessError

ADMIN_GROUP = 'elite_clearance.group_clearance_admin'
USER_GROUP = 'elite_clearance.group_clearance_user'

# The two the owner asked for. Odoo knows many more; offering them all
# would offer the Clearance Administrator a choice nobody translated.
LANGUAGES = [('en_US', "English"), ('fr_FR', "French")]


class ClearanceUserLanguageWizard(models.TransientModel):
    _name = 'clearance.user.language.wizard'
    _description = "User Languages"

    line_ids = fields.One2many(
        'clearance.user.language.wizard.line', 'wizard_id',
        string="Users")

    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        group = self.env.ref(USER_GROUP)
        users = self.env['res.users'].search(
            [('share', '=', False), ('active', '=', True),
             ('all_group_ids', 'in', group.id)], order='name')
        vals['line_ids'] = [
            fields.Command.create({
                'user_id': user.id,
                'lang': user.lang if user.lang in dict(LANGUAGES) else 'en_US',
            })
            for user in users
        ]
        return vals

    def _check_admin(self):
        # env.user, not env.su: a plain user's sudo() must not be a way in
        if not self.env.user.has_group(ADMIN_GROUP):
            raise AccessError(self.env._(
                "Only a Clearance Administrator may set users' languages."))

    @api.model
    def _ensure_active(self, codes):
        """Activate the languages not yet active, loading every installed
        module's translations for them - Odoo's own installer, under
        sudo, because activating a language is an administrator's act."""
        Lang = self.env['res.lang'].sudo()
        missing = Lang.with_context(active_test=False).search(
            [('code', 'in', list(codes)), ('active', '=', False)])
        if missing:
            self.env['base.language.install'].sudo().create({
                'lang_ids': [fields.Command.set(missing.ids)],
            }).lang_install()

    def action_apply(self):
        self.ensure_one()
        self._check_admin()
        changed = self.line_ids.filtered(
            lambda l: l.lang and l.user_id.lang != l.lang)
        if changed:
            self._ensure_active(set(changed.mapped('lang')))
            for line in changed:
                line.user_id.sudo().write({'lang': line.lang})
        # The administrator's own screen only changes language on reload.
        return {'type': 'ir.actions.client', 'tag': 'reload'}


class ClearanceUserLanguageWizardLine(models.TransientModel):
    _name = 'clearance.user.language.wizard.line'
    _description = "User Language"
    _order = 'id'

    wizard_id = fields.Many2one(
        'clearance.user.language.wizard', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string="User", required=True,
                              readonly=True)
    login = fields.Char(related='user_id.login', string="Login")
    lang = fields.Selection(LANGUAGES, string="Language", required=True)
