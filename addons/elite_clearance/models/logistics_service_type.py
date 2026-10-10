import re

from odoo import api, fields, models
from odoo.exceptions import UserError


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

    # Owner spec 10/10/2026: the files opened in the old system took
    # numbers this database has never seen. Keying the last of them here
    # makes the next file opened in Odoo carry on from it - 2026IM0019
    # keyed, 2026IM0020 issued.
    legacy_last_file_ref = fields.Char(
        string="Last File Number in Legacy System",
        help="The reference of the last file this service opened in the old "
             "system, e.g. 2026IM0019. The next file opened here takes the "
             "number after it. Undisclosed clients keep their own series.")

    document_ids = fields.One2many(
        'logistics.service.type.document', 'service_type_id',
        string="Required Documents", copy=True,
    )
    document_count = fields.Integer(compute='_compute_document_count')

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        "A service type with this code already exists for this company.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        services = super().create(vals_list)
        services.filtered('legacy_last_file_ref')._continue_legacy_numbering()
        return services

    def write(self, vals):
        res = super().write(vals)
        if vals.get('legacy_last_file_ref'):
            self._continue_legacy_numbering()
        return res

    def _continue_legacy_numbering(self):
        """Point this service's file series at the number after the last
        one the old system issued.

        The reference is read, not trusted: it must be the year, this
        service's code and a number, and no file already opened here may
        hold a number past it - the series would otherwise hand out a
        reference that is taken.
        """
        File = self.env['logistics.file']
        for service in self:
            ref = (service.legacy_last_file_ref or '').strip().upper()
            code = (service.code or '').upper()
            match = re.fullmatch(r'(\d{4})%s(\d+)' % re.escape(code), ref)
            if not match:
                raise UserError(self.env._(
                    "%(ref)s is not a %(service)s file number. It reads as "
                    "the year, the service code and the number, e.g. "
                    "%(example)s.",
                    ref=service.legacy_last_file_ref, service=service.name,
                    example="2026%s0019" % code))
            year, last = match.group(1), int(match.group(2))
            if ref != service.legacy_last_file_ref:
                super(LogisticsServiceType, service).write(
                    {'legacy_last_file_ref': ref})
            company = service.company_id or self.env.company
            prefix = "%s%s" % (year, code)
            taken = File.sudo().with_context(active_test=False).search([
                ('name', '=like', prefix + '%'),
                ('company_id', '=', company.id)])
            numbers = [int(name[len(prefix):]) for name in taken.mapped('name')
                       if name[len(prefix):].isdigit()]
            highest = max(numbers, default=0)
            if highest > last:
                raise UserError(self.env._(
                    "%(prefix)s%(n)04d has already been opened here, so the "
                    "series cannot go back to %(ref)s. Key %(prefix)s%(n)04d "
                    "or a later number.",
                    prefix=prefix, n=highest, ref=ref))
            sequence = File._get_reference_sequence('file', service, company)
            date_from, date_to = "%s-01-01" % year, "%s-12-31" % year
            date_range = sequence.date_range_ids.filtered(
                lambda d: str(d.date_from) == date_from
                and str(d.date_to) == date_to)
            if not date_range:
                # Create, THEN write: create() ignores number_next, only
                # write() restarts the PostgreSQL sequence behind it.
                date_range = self.env['ir.sequence.date_range'].sudo().create({
                    'sequence_id': sequence.id,
                    'date_from': date_from, 'date_to': date_to})
            date_range.sudo().write({'number_next': last + 1})

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
