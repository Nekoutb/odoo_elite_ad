from odoo import fields, models


class ClearanceDocumentsMixin(models.AbstractModel):
    """A record whose supporting documents can be dropped on the screen.

    The field is COMPUTED over the attachments that already point at the
    record - the chatter's included - and inversed by pointing new ones at
    it, so however a document arrived there is only ever one set of them.
    A file dropped on a form that has not been saved yet is uploaded
    against the model with no record (res_id 0); the inverse adopts it the
    moment the record exists.
    """

    _name = 'clearance.documents.mixin'
    _description = "Clearance Supporting Documents"

    attachment_ids = fields.Many2many(
        'ir.attachment', string="Documents",
        compute='_compute_attachment_ids', inverse='_inverse_attachment_ids',
        help="Drop files anywhere on this screen, or use Upload.")

    # The two kinds a disbursement tells apart (owner, 01/10/2026). A
    # document with no kind is a request document: every one uploaded
    # before the kind existed was.
    REQUEST_KINDS = ('request', False)

    def _clearance_documents_domain(self, ids, kinds=None):
        domain = [('res_model', '=', self._name), ('res_id', 'in', ids),
                  ('res_field', '=', False)]
        if kinds is not None:
            domain.append(('clearance_kind', 'in', list(kinds)))
        return domain

    def _clearance_compute_documents(self, field, kinds=None):
        Attachment = self.env['ir.attachment']
        by_record = {}
        real = self.filtered(lambda rec: isinstance(rec.id, int))
        if real:
            for att in Attachment.search(
                    self._clearance_documents_domain(real.ids, kinds)):
                by_record.setdefault(att.res_id, []).append(att.id)
        for record in self:
            record[field] = Attachment.browse(
                by_record.get(record.id, [])
                if isinstance(record.id, int) else [])

    def _clearance_adopt_documents(self, field, kinds=None, kind=None):
        """Adopt what was added; delete what was taken away.

        One removed with the widget's cross is deleted: the person who
        dropped the wrong file meant it gone, not orphaned. `kind` is
        stamped on what is adopted, so a document dropped in the payment
        box is payment evidence from then on.
        """
        Attachment = self.env['ir.attachment']
        for record in self:
            current = Attachment.search(
                self._clearance_documents_domain([record.id], kinds))
            wanted = record[field]
            added = wanted - current
            if added:
                vals = {'res_model': self._name, 'res_id': record.id}
                if kind:
                    vals['clearance_kind'] = kind
                added.write(vals)
                if kind != 'payment':
                    record._clearance_documents_added(added)
            removed = current - wanted
            if removed:
                removed.unlink()

    def _compute_attachment_ids(self):
        self._clearance_compute_documents('attachment_ids')

    def _inverse_attachment_ids(self):
        self._clearance_adopt_documents('attachment_ids')

    def _clearance_documents_added(self, attachments):
        """A hook for whatever the arrival of a document means to the
        record. Nothing, unless a model says otherwise."""
        return
