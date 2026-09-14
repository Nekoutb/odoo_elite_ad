from odoo import fields, models


class AccountPayment(models.Model):
    """A client's payment that belongs to a clearance file.

    Advances are common on this work: the client puts money up before the
    duties are paid, and the invoice has to show it so that what is really
    still owed is on the face of the document (owner spec 15/09/2026).

    The link is the journal entry's, not the payment's - account.payment
    in Odoo 19 holds a plain move_id rather than delegating to it - so
    this is a stored related, which is what makes the file's advances
    searchable and groupable.
    """

    _inherit = 'account.payment'

    logistics_file_id = fields.Many2one(
        related='move_id.logistics_file_id', store=True, index=True,
        string="Clearance File", readonly=True,
        help="The clearance file this payment was received against. Every "
             "line of it carries that file's analytic account, like "
             "everything else the file touches.")
