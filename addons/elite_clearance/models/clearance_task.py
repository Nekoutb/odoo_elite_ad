from odoo import api, fields, models, tools

# Every checkpoint in the module, as one queue. The rows are a database
# view over the files and expenses that are actually waiting - nothing is
# stored, nothing can drift out of step with the records themselves.
#
# Each kind names the groups allowed to act on it. `_search` narrows every
# read to the kinds the reader can actually do something about, so the one
# screen shows a different list to each role without a menu per role.

KIND_GROUPS = {
    'expense_approve': (
        'elite_clearance.group_clearance_ops_manager',
        'elite_clearance.group_clearance_customer_service_manager',
        'elite_clearance.group_clearance_transit_manager'),
    'settlement_key': ('elite_clearance.group_clearance_finance',),
    'settlement_approve': ('elite_clearance.group_clearance_finance_manager',),
    'disburse_cash': ('elite_clearance.group_clearance_cashier',),
    'disburse_bank': ('elite_clearance.group_clearance_treasury',),
    'justification_approve': ('elite_clearance.group_clearance_ops_manager',),
    'doc_waiver': ('elite_clearance.group_clearance_manager',
                   'elite_clearance.group_clearance_ops_manager'),
    'advance_waiver': ('elite_clearance.group_clearance_ops_manager',),
    'recharge_ops': ('elite_clearance.group_clearance_ops_manager',),
    'recharge_gm': ('elite_clearance.group_clearance_manager',),
    'reopen_imported': ('elite_clearance.group_clearance_ops_manager',),
    'ops_close': ('elite_clearance.group_clearance_ops_manager',),
    'billing': ('elite_clearance.group_clearance_billing',),
    'billing_service': ('elite_clearance.group_clearance_ops_manager',),
}

KINDS = [
    ('expense_approve', "Approve expense"),
    ('settlement_key', "Prepare settlement"),
    ('settlement_approve', "Approve settlement"),
    ('disburse_cash', "Pay from cash"),
    ('disburse_bank', "Pay from bank"),
    ('justification_approve', "Approve justification"),
    ('doc_waiver', "Approve document waiver"),
    ('advance_waiver', "Approve advance waiver"),
    ('recharge_ops', "Approve recharge (Operations)"),
    ('recharge_gm', "Approve undercharge (General Manager)"),
    ('reopen_imported', "Approve reopening"),
    ('ops_close', "Close for operations"),
    ('billing', "Bill the file"),
    ('billing_service', "Approve a billable service"),
]


class ClearanceTask(models.Model):
    _name = 'clearance.task'
    _description = "Clearance Task"
    _auto = False
    _order = 'date_deadline, id'

    name = fields.Char(readonly=True)
    kind = fields.Selection(KINDS, readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    file_id = fields.Many2one('logistics.file', readonly=True)
    partner_id = fields.Many2one('res.partner', string="Client", readonly=True)
    detail = fields.Char(string="What is waiting", readonly=True)
    amount = fields.Monetary(readonly=True, currency_field='currency_id')
    date_deadline = fields.Date(string="Waiting since", readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)

    # ------------------------------------------------------------------
    @property
    def _table_query(self):
        return """
            SELECT * FROM (%s) AS clearance_task_union
        """ % " UNION ALL ".join(self._task_selects())

    @staticmethod
    def _text(column):
        """Read a name column whether it is varchar or jsonb.

        Odoo stores a translate=True Char as jsonb, and this view UNIONs
        name columns from three different tables: the moment one of them
        becomes translated, Postgres refuses the whole query and My Tasks
        dies for everyone. to_jsonb() of a jsonb value is itself, so the
        ->> extracts the English text; to_jsonb() of a varchar is a JSON
        *string*, where ->> returns NULL and the COALESCE falls through to
        the plain value. Both shapes come out as text, which unions.
        """
        return ("COALESCE(to_jsonb({col}) ->> 'en_US', {col}::text)"
                .format(col=column))

    def _task_selects(self):
        # ids are synthetic: kind ordinal * 10^7 + record id, so every row
        # in the union is unique and stable between reads.
        expense = """
            SELECT (%(offset)s * 10000000 + e.id) AS id,
                   %(name_expr)s AS name,
                   '%(kind)s' AS kind,
                   'logistics.expense' AS res_model,
                   e.id AS res_id,
                   e.file_id AS file_id,
                   f.partner_id AS partner_id,
                   e.description AS detail,
                   e.amount AS amount,
                   e.date_requested AS date_deadline,
                   e.company_id AS company_id,
                   c.currency_id AS currency_id
              FROM logistics_expense e
              JOIN logistics_file f ON f.id = e.file_id
              JOIN res_company c ON c.id = e.company_id
             WHERE e.state = '%(state)s' AND %(extra)s
        """
        file_task = """
            SELECT (%(offset)s * 10000000 + f.id) AS id,
                   %(name_expr)s AS name,
                   '%(kind)s' AS kind,
                   'logistics.file' AS res_model,
                   f.id AS res_id,
                   f.id AS file_id,
                   f.partner_id AS partner_id,
                   %(detail)s AS detail,
                   %(amount)s AS amount,
                   f.create_date::date AS date_deadline,
                   f.company_id AS company_id,
                   c.currency_id AS currency_id
              FROM logistics_file f
              JOIN res_company c ON c.id = f.company_id
             WHERE %(where)s
        """
        expense = expense.replace('%(name_expr)s', self._text('e.name'))
        file_task = file_task.replace('%(name_expr)s', self._text('f.name'))
        selects = [
            expense % dict(offset=1, kind='expense_approve',
                           state='submitted', extra='TRUE'),
            expense % dict(offset=2, kind='settlement_key',
                           state='approved', extra='TRUE'),
            expense % dict(offset=3, kind='settlement_approve',
                           state='settlement_submitted', extra='TRUE'),
            # the money leaves through the cashier or the treasury
            # depending on the journal, so they are two different queues
            expense % dict(
                offset=4, kind='disburse_cash', state='settlement_approved',
                extra="EXISTS (SELECT 1 FROM account_journal j "
                      "WHERE j.id = e.journal_id AND j.type = 'cash')"),
            expense % dict(
                offset=5, kind='disburse_bank', state='settlement_approved',
                extra="(e.journal_id IS NULL OR EXISTS (SELECT 1 FROM "
                      "account_journal j WHERE j.id = e.journal_id "
                      "AND j.type <> 'cash'))"),
            expense % dict(offset=6, kind='justification_approve',
                           state='justification_submitted', extra='TRUE'),
            file_task % dict(
                offset=7, kind='doc_waiver',
                detail="'Mandatory documents are missing'",
                amount='0.0', where="f.waiver_state = 'requested'"),
            file_task % dict(
                offset=8, kind='advance_waiver',
                detail="'Staff advances are unjustified'",
                amount='f.unjustified_advance_total',
                where="f.advance_waiver_state = 'requested'"),
            file_task % dict(
                offset=9, kind='recharge_ops',
                detail="'Recharge adjustment awaiting Operations'",
                amount='f.recharge_amount',
                where="f.recharge_state = 'requested'"),
            file_task % dict(
                offset=10, kind='recharge_gm',
                detail="'Undercharge awaiting the General Manager'",
                amount='f.recharge_amount',
                where="f.recharge_state = 'ops_approved'"),
            file_task % dict(
                offset=11, kind='reopen_imported',
                detail="'Reopening requested for an imported file'",
                amount='0.0', where="f.reopen_request_state = 'requested'"),
            file_task % dict(
                offset=12, kind='ops_close',
                detail="'Work is done; close for operations'",
                amount='f.oop_total', where="f.state = 'in_progress'"),
            file_task % dict(
                offset=13, kind='billing',
                detail="'OK for billing'", amount='f.oop_total',
                where="f.state = 'ops_closed' AND f.invoice_id IS NULL"),
            # a proposed revenue line, waiting for Operations to allow it
            """
            SELECT (14 * 10000000 + s.id) AS id,
                   COALESCE(to_jsonb(s.name) ->> 'en_US', s.name::text) AS name,
                   'billing_service' AS kind,
                   'logistics.billing.service' AS res_model,
                   s.id AS res_id,
                   NULL::integer AS file_id,
                   NULL::integer AS partner_id,
                   'New billable service awaiting approval' AS detail,
                   s.default_amount AS amount,
                   s.create_date::date AS date_deadline,
                   s.company_id AS company_id,
                   c.currency_id AS currency_id
              FROM logistics_billing_service s
              JOIN res_company c ON c.id = s.company_id
             WHERE s.state = 'draft' AND s.active = TRUE
            """,
        ]
        return selects

    # ------------------------------------------------------------------
    def _allowed_kinds(self):
        """The kinds this user can actually act on."""
        if self.env.su:
            return [kind for kind, _label in KINDS]
        return [kind for kind, groups in KIND_GROUPS.items()
                if any(self.env.user.has_group(g) for g in groups)]

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        # This model is a view over other tables, and the ORM has no way to
        # know that: it flushes pending writes for the models a query
        # names, and this query names none of them. Without these flushes a
        # file whose state changed a moment ago is simply missing from the
        # queue - the write is still sitting in the cache while the SQL
        # reads the table underneath it.
        self.env['logistics.file'].flush_model()
        self.env['logistics.expense'].flush_model()
        self.env['account.journal'].flush_model()
        self.env['logistics.billing.service'].flush_model()
        # Narrow every read, so the one screen is a different list for each
        # role and nobody sees a queue they cannot act on.
        domain = [('kind', 'in', self._allowed_kinds())] + list(domain or [])
        return super()._search(domain, offset=offset, limit=limit,
                               order=order, **kwargs)

    # ------------------------------------------------------------------
    def action_open(self):
        """Go to the record the task is about."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }
