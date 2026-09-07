from odoo import api, models


class IrAttachment(models.Model):
    """Uploading a supporting document is what dates its arrival.

    The justification of a staff advance needs a document, and the owner
    wants the date that document appeared - not the date somebody later
    remembered to type. The upload itself stamps the expense, once, on the
    first document.
    """

    _inherit = 'ir.attachment'

    @api.model_create_multi
    def create(self, vals_list):
        attachments = super().create(vals_list)
        ids = {
            att.res_id for att in attachments
            if att.res_model == 'logistics.expense' and att.res_id
        }
        if ids:
            self.env['logistics.expense'].browse(
                sorted(ids))._stamp_documents_received()
        return attachments
