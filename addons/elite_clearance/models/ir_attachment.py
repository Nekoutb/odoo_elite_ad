from odoo import api, fields, models


class IrAttachment(models.Model):
    """Uploading a supporting document is what dates its arrival.

    The justification of a staff advance needs a document, and the owner
    wants the date that document appeared - not the date somebody later
    remembered to type. The upload itself stamps the expense, once, on the
    first document.
    """

    _inherit = 'ir.attachment'

    # What a document on a disbursement IS (owner, 01/10/2026): the
    # receipt or quote that supported the REQUEST, or the EVIDENCE that
    # the money left. Empty means request - every document before this
    # field existed was one.
    clearance_kind = fields.Selection(
        [('request', "Supporting document (request)"),
         ('payment', "Payment evidence")],
        string="Clearance Document Kind", index=True)

    @api.model_create_multi
    def create(self, vals_list):
        attachments = super().create(vals_list)
        # payment evidence dates the payment, not the justification
        ids = {
            att.res_id for att in attachments
            if att.res_model == 'logistics.expense' and att.res_id
            and att.clearance_kind != 'payment'
        }
        if ids:
            self.env['logistics.expense'].browse(
                sorted(ids))._stamp_documents_received()
        return attachments
