from odoo import models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _build_wkhtmltopdf_args(self, *args, **kwargs):
        """Tell wkhtmltopdf the bytes it is reading are UTF-8.

        Odoo never passes --encoding. It relies on the <meta charset> in
        web.minimal_layout, which sits AFTER two inlined asset bundles -
        tens of kilobytes past the window a parser reads a charset hint
        in. wkhtmltopdf therefore falls back to Latin-1 and every accented
        character in the PDF comes out as mojibake: N° prints as NÂ°,
        Catégorie as CatÃ©gorie, and a non-breaking space as Â.

        Saying it outright costs nothing and is right for every report in
        the database, not just ours: Odoo is UTF-8 from end to end.
        """
        command_args = super()._build_wkhtmltopdf_args(*args, **kwargs)
        if '--encoding' not in command_args:
            command_args.extend(['--encoding', 'utf-8'])
        return command_args
