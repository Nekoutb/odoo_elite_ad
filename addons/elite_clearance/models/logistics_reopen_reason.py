"""Why a file is reopened, from a list (owner, 16/10/2026).

A closed file is reopened for a reason the owner wants to count later -
more cost to bill, a billing correction, a credit note. The reasons are a
list kept under Configuration, chosen on every reopening (the closed
file's dialog and the imported file's request alike), and each reopening
is one row of `logistics.file.reopening`, which is what Reporting ->
Reopenings counts: a file reopened twice is two rows, not one flag.
"""

from odoo import api, fields, models

REOPEN_TARGETS = [
    ('in_progress', "Back to operations, to add costs"),
    ('ops_closed', "Back to billing"),
]


class LogisticsReopenReason(models.Model):
    _name = 'logistics.reopen.reason'
    _description = "File Reopening Reason"
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    target_state = fields.Selection(
        REOPEN_TARGETS, string="Usually Sends the File",
        help="Pre-selected on the reopening dialog of a closed file when "
             "this reason is chosen; the person reopening may still change "
             "it. Empty: nothing is pre-selected.")
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda s: s.env.company)

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        "A reopening reason with this name already exists.")


class LogisticsFileReopening(models.Model):
    """One row per reopening: what Reporting -> Reopenings counts."""
    _name = 'logistics.file.reopening'
    _description = "File Reopening"
    _order = 'date desc, id desc'
    _rec_name = 'file_id'

    file_id = fields.Many2one(
        'logistics.file', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one(
        related='file_id.partner_id', store=True, string="Client")
    service_type_id = fields.Many2one(
        related='file_id.service_type_id', store=True, string="Service Type")
    customs_regime = fields.Selection(
        related='file_id.customs_regime', store=True, string="Customs Regime")
    reason_id = fields.Many2one(
        'logistics.reopen.reason', required=True, string="Reason",
        ondelete='restrict')
    note = fields.Text(string="Explanation")
    target_state = fields.Selection(
        [('in_progress', "Operations"), ('ops_closed', "Billing")],
        string="Reopened To", required=True)
    from_state = fields.Selection(
        [('ops_closed', "OK for Billing"), ('done', "Closed"),
         ('imported', "Imported")],
        string="Reopened From", required=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    user_id = fields.Many2one(
        'res.users', string="Approved By", default=lambda s: s.env.user,
        required=True)
    company_id = fields.Many2one(
        related='file_id.company_id', store=True)
