from odoo import fields, models


class LogisticsPort(models.Model):
    """Port (or dry port / airport) a clearance file is handled at.

    Kribi, Douala, Tiko, Yaounde in the legacy data. Shared across
    companies on purpose: a port is geography, not an accounting entity.
    """

    _name = 'logistics.port'
    _description = "Port"
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(help="Short code, e.g. KRB, DLA.")
    city = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'UNIQUE(name)', "A port with this name already exists.")
