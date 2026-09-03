from odoo import api, fields, models


class HrEmployee(models.Model):
    """Staff who may hold a disbursement advance.

    Advances are carried on ONE account — 421101 Personnel débours avancés —
    with the staff member's work contact as the auxiliary. That is Odoo's
    native subsidiary-ledger mechanism, the same one receivables and payables
    use, so there is deliberately no per-employee account in the chart: each
    person's own ledger and running balance come from the Partner Ledger on
    421101, and reconciliation happens per partner.
    """

    _inherit = 'hr.employee'

    clearance_advance_ids = fields.One2many(
        'logistics.expense', 'employee_id', string="Clearance Advances",
    )
    clearance_currency_id = fields.Many2one(
        related='company_id.currency_id', string="Clearance Currency",
    )
    clearance_advance_count = fields.Integer(
        compute='_compute_clearance_advances', string="Advances Held",
    )
    clearance_advance_balance = fields.Monetary(
        compute='_compute_clearance_advances',
        currency_field='clearance_currency_id',
        string="Unjustified Advances",
        help="Advanced to this staff member and settled, but not yet "
             "justified with supporting documents — the balance standing "
             "against them on 421101 Personnel débours avancés. A clearance "
             "file carrying any of this cannot be billed unless an "
             "Operations Manager waives it in writing.",
    )

    @api.depends('clearance_advance_ids.state',
                 'clearance_advance_ids.amount',
                 'clearance_advance_ids.payment_mode')
    def _compute_clearance_advances(self):
        for employee in self:
            outstanding = employee.clearance_advance_ids.filtered(
                lambda e: e.payment_mode == 'advance' and e.state == 'settled')
            employee.clearance_advance_count = len(outstanding)
            employee.clearance_advance_balance = sum(outstanding.mapped('amount'))

    def _clearance_auxiliary_partner(self):
        """The partner that carries this employee's advances on 421101.

        hr creates the work contact only as a side effect of writing the work
        e-mail or phone (_inverse_work_contact_details -> _create_work_contacts),
        so a staff member keyed with nothing but a name can have none — and
        then there is no auxiliary to post the advance against. Create it on
        demand rather than refusing at settlement time.

        sudo(): the auxiliary is a technical identity the system owns. A
        finance user settling an advance is not choosing to create a contact.
        """
        self.ensure_one()
        if not self.work_contact_id:
            self.sudo().work_contact_id = self.env['res.partner'].sudo().create({
                'name': self.name,
                'company_id': self.company_id.id,
            })
        return self.work_contact_id

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        # "Each staff created will have a specific staff account auxiliarised
        # to 421101": under partner-as-auxiliary that account IS (421101,
        # this contact), so the contact must exist from the moment the staff
        # record does — not first be conjured up mid-settlement.
        for employee in employees:
            employee._clearance_auxiliary_partner()
        return employees

    def action_open_clearance_advances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Clearance Advances"),
            'res_model': 'logistics.expense',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id),
                       ('payment_mode', '=', 'advance')],
            'context': {'default_employee_id': self.id,
                        'default_payment_mode': 'advance'},
        }
