from odoo import api, fields, models


class LogisticsServiceType(models.Model):
    """A service offering (import clearance, export, transit, door delivery).

    Carries the document checklist template that every file of this type
    inherits at creation.
    """

    _name = 'logistics.service.type'
    _description = "Clearance Service Type"
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True,
    )

    commission_rate = fields.Float(
        string="Commission Rate (%)",
        default=2.0,
        digits=(5, 2),
        help="Percentage of the file's out-of-pocket total invoiced as the "
             "clearance commission. Billed as its own line, alongside the "
             "manually keyed customs service fee.",
    )

    document_ids = fields.One2many(
        'logistics.service.type.document', 'service_type_id',
        string="Required Documents", copy=True,
    )
    document_count = fields.Integer(compute='_compute_document_count')

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        "A service type with this code already exists for this company.",
    )

    @api.depends('document_ids')
    def _compute_document_count(self):
        # Aggregate in PostgreSQL rather than looping over One2many fields.
        counts = dict(self.env['logistics.service.type.document']._read_group(
            domain=[('service_type_id', 'in', self.ids)],
            groupby=['service_type_id'],
            aggregates=['__count'],
        ))
        for service_type in self:
            service_type.document_count = counts.get(service_type, 0)


class LogisticsServiceTypeDocument(models.Model):
    """One line of a service type's checklist template."""

    _name = 'logistics.service.type.document'
    _description = "Service Type Required Document"
    _order = 'sequence, id'

    service_type_id = fields.Many2one(
        'logistics.service.type', required=True, ondelete='cascade', index=True,
    )
    document_type_id = fields.Many2one(
        'logistics.document.type', required=True, ondelete='restrict',
    )
    sequence = fields.Integer(default=10)
    is_mandatory = fields.Boolean(
        string="Mandatory", default=True,
        help="A file cannot start work while a mandatory document is missing, "
             "unless a manager approves a waiver.",
    )
    note = fields.Char()

    _document_per_service_uniq = models.Constraint(
        'UNIQUE(service_type_id, document_type_id)',
        "This document is already listed for this service type.",
    )
