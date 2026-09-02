from odoo import fields, models


class LogisticsDocumentType(models.Model):
    """Master list of documents a clearance file may require."""

    _name = 'logistics.document.type'
    _description = "Clearance Document Type"
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Short code used on checklists and reports, e.g. BL, INV, PL, COO.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True,
    )

    # Odoo 19 form. The attribute name (minus the underscore) becomes the
    # constraint name; the PostgreSQL identifier is "{table}_{name}".
    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        "A document type with this code already exists for this company.",
    )
