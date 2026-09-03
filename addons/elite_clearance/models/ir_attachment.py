from odoo import api, fields, models


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
            # sudo(): the stamp is the system recording a fact, not the
            # uploader choosing to write on the expense.
            expenses = self.env['logistics.expense'].sudo().browse(sorted(ids))
            now = fields.Datetime.now()
            for expense in expenses.exists():
                if not expense.date_documents_submitted:
                    expense.date_documents_submitted = now
        return attachments
