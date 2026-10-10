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
         ('payment', "Payment evidence"),
         # the petty-cash voucher (owner 10/10/2026): the one the system
         # prints at Disburse / Pay, and the signed copy the cashier
         # brings back
         ('voucher', "Cash voucher (generated)"),
         ('signed', "Cash voucher (signed)")],
        string="Clearance Document Kind", index=True)

    # The kinds that are about the PAYMENT, not the request: none of them
    # dates the arrival of supporting documents.
    PAYMENT_KINDS = ('payment', 'voucher', 'signed')

    @api.model_create_multi
    def create(self, vals_list):
        attachments = super().create(vals_list)
        # payment evidence dates the payment, not the justification
        ids = {
            att.res_id for att in attachments
            if att.res_model == 'logistics.expense' and att.res_id
            and att.clearance_kind not in self.PAYMENT_KINDS
        }
        if ids:
            self.env['logistics.expense'].browse(
                sorted(ids))._stamp_documents_received()
        return attachments
