from odoo import api, fields, models

# How long each step in the workflow is supposed to take, and how long it
# actually took. The point is the gap: an advance requested on Monday and
# paid on Friday is not visible anywhere in a file's own form, and it is
# exactly the thing somebody needs to chase.

STEPS = [
    # --- the file -----------------------------------------------------
    ('file_start', "File: opened → work started"),
    ('file_waiver', "File: document waiver requested → approved"),
    ('file_ops_close', "File: work started → closed for operations"),
    ('file_bill', "File: closed for operations → invoiced"),
    ('file_adv_waiver', "File: advance waiver requested → approved"),
    ('file_recharge', "File: recharge adjustment requested → approved"),
    ('file_reopen', "File: reopening requested → approved"),
    # --- a supporting document ----------------------------------------
    ('doc_receive', "Document: requested → received"),
    # --- an out-of-pocket expense -------------------------------------
    ('exp_submit', "Expense: keyed → submitted"),
    ('exp_approve', "Expense: submitted → approved"),
    ('exp_settle_key', "Expense: approved → settlement prepared"),
    ('exp_settle_approve', "Expense: settlement prepared → approved"),
    ('exp_pay', "Expense: settlement approved → paid"),
    ('exp_justify_docs', "Advance: paid → supporting documents submitted"),
    ('exp_justify', "Advance: documents submitted → justified"),
]

DEFAULT_TARGET_DAYS = {
    'file_start': 2, 'file_waiver': 1, 'file_ops_close': 10,
    'file_bill': 2, 'file_adv_waiver': 2, 'file_recharge': 2,
    'file_reopen': 2, 'doc_receive': 3, 'exp_submit': 1,
    'exp_approve': 1, 'exp_settle_key': 1, 'exp_settle_approve': 1,
    'exp_pay': 2, 'exp_justify_docs': 3, 'exp_justify': 2,
}


class ClearanceTurnaroundTarget(models.Model):
    """How many days a step is allowed to take before it is chased."""
    _name = 'clearance.turnaround.target'
    _description = "Turnaround Target"
    _order = 'step'

    step = fields.Selection(STEPS, required=True)
    target_days = fields.Integer(
        string="Target (days)", required=True, default=2,
        help="Working from the moment the step became possible to the "
             "moment it was done. Zero means same day.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda s: s.env.company)

    _step_company_uniq = models.Constraint(
        'UNIQUE(step, company_id)',
        "That step already has a target for this company.")

    def _display_name_compute(self):
        return dict(STEPS).get(self.step, self.step)


class ClearanceTurnaround(models.Model):
    """One row per step of every record, measured.

    A database view: nothing is stored, so it can never disagree with the
    timestamps the workflow actually wrote. An unfinished step measures
    against now(), which is what makes an overdue queue possible - a step
    that has not happened is precisely the one worth chasing.
    """
    _name = 'clearance.turnaround'
    _description = "Turnaround"
    _auto = False
    _order = 'started desc'

    name = fields.Char(readonly=True)
    step = fields.Selection(STEPS, readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    file_id = fields.Many2one('logistics.file', readonly=True)
    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    file_state = fields.Char(string="File Status", readonly=True)
    started = fields.Datetime(string="Waiting since", readonly=True)
    completed = fields.Datetime(string="Done at", readonly=True)
    is_done = fields.Boolean(readonly=True)
    hours_taken = fields.Float(
        string="Hours", readonly=True, group_operator='avg')
    days_taken = fields.Float(
        string="Days", readonly=True, group_operator='avg',
        help="Elapsed so far when the step is not finished.")
    target_days = fields.Integer(readonly=True)
    is_late = fields.Boolean(string="Over target", readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    # ------------------------------------------------------------------
    @property
    def _table_query(self):
        return "SELECT * FROM (%s) AS clearance_turnaround_union" % (
            " UNION ALL ".join(self._turnaround_selects()))

    @staticmethod
    def _text(column):
        """Read a name column whether it is varchar or jsonb.

        Same guard as clearance.task: a translated Char is stored as jsonb
        and would break the UNION outright. See CLAUDE.md.
        """
        return ("COALESCE(to_jsonb({col}) ->> 'en_US', {col}::text)"
                .format(col=column))

    def _turnaround_selects(self):
        file_sql = """
            SELECT (%(offset)s * 100000000 + f.id) AS id,
                   {fname} AS name,
                   '%(step)s' AS step,
                   'logistics.file' AS res_model,
                   f.id AS res_id,
                   f.id AS file_id,
                   f.partner_id AS partner_id,
                   f.state AS file_state,
                   %(started)s AS started,
                   %(done)s AS completed,
                   f.company_id AS company_id
              FROM logistics_file f
             WHERE %(started)s IS NOT NULL AND %(extra)s
        """.format(fname=self._text('f.name'))

        expense_sql = """
            SELECT (%(offset)s * 100000000 + e.id) AS id,
                   {ename} AS name,
                   '%(step)s' AS step,
                   'logistics.expense' AS res_model,
                   e.id AS res_id,
                   e.file_id AS file_id,
                   f.partner_id AS partner_id,
                   f.state AS file_state,
                   %(started)s AS started,
                   %(done)s AS completed,
                   e.company_id AS company_id
              FROM logistics_expense e
              JOIN logistics_file f ON f.id = e.file_id
             WHERE %(started)s IS NOT NULL AND e.is_legacy IS NOT TRUE
        """.format(ename=self._text('e.name'))

        document_sql = """
            SELECT (%(offset)s * 100000000 + d.id) AS id,
                   {dname} AS name,
                   'doc_receive' AS step,
                   'logistics.file.document' AS res_model,
                   d.id AS res_id,
                   d.file_id AS file_id,
                   f.partner_id AS partner_id,
                   f.state AS file_state,
                   d.create_date AS started,
                   d.date_received AS completed,
                   f.company_id AS company_id
              FROM logistics_file_document d
              JOIN logistics_file f ON f.id = d.file_id
              JOIN logistics_document_type t ON t.id = d.document_type_id
             WHERE d.create_date IS NOT NULL
        """.format(dname=self._text('t.name'))

        selects = [
            file_sql % dict(offset=1, step='file_start',
                            started='f.create_date', done='f.date_started',
                            extra='TRUE'),
            file_sql % dict(offset=2, step='file_waiver',
                            started='f.waiver_requested_date',
                            done='f.waiver_date', extra='TRUE'),
            file_sql % dict(offset=3, step='file_ops_close',
                            started='f.date_started',
                            done='f.date_ops_closed', extra='TRUE'),
            file_sql % dict(offset=4, step='file_bill',
                            started='f.date_ops_closed',
                            done='f.date_billed', extra='TRUE'),
            file_sql % dict(offset=5, step='file_adv_waiver',
                            started='f.advance_waiver_requested_date',
                            done='f.advance_waiver_date', extra='TRUE'),
            file_sql % dict(offset=6, step='file_recharge',
                            started='f.recharge_requested_date',
                            done='f.recharge_approved_date', extra='TRUE'),
            file_sql % dict(offset=7, step='file_reopen',
                            started='f.reopen_request_date',
                            done=("CASE WHEN f.reopen_request_state = 'approved'"
                                  " THEN f.write_date END"), extra='TRUE'),
            expense_sql % dict(offset=8, step='exp_submit',
                               started='e.date_requested::timestamp',
                               done='e.date_submitted'),
            expense_sql % dict(offset=9, step='exp_approve',
                               started='e.date_submitted',
                               done='e.date_approved'),
            expense_sql % dict(offset=10, step='exp_settle_key',
                               started='e.date_approved',
                               done='e.date_settlement_submitted'),
            expense_sql % dict(offset=11, step='exp_settle_approve',
                               started='e.date_settlement_submitted',
                               done='e.date_settlement_approved'),
            expense_sql % dict(offset=12, step='exp_pay',
                               started='e.date_settlement_approved',
                               done='e.date_settled'),
            expense_sql % dict(offset=13, step='exp_justify_docs',
                               started='e.date_settled',
                               done='e.date_documents_submitted'),
            expense_sql % dict(offset=14, step='exp_justify',
                               started='e.date_justification_submitted',
                               done='e.date_justified'),
            document_sql % dict(offset=15),
        ]
        # Wrap each one so the arithmetic and the target are computed once,
        # against the company's configured allowance for that step.
        return [self._measured(select) for select in selects]

    @staticmethod
    def _measured(select):
        return """
            SELECT base.id, base.name, base.step, base.res_model,
                   base.res_id, base.file_id, base.partner_id,
                   base.file_state, base.started, base.completed,
                   (base.completed IS NOT NULL) AS is_done,
                   EXTRACT(EPOCH FROM (
                       COALESCE(base.completed, now()) - base.started
                   )) / 3600.0 AS hours_taken,
                   EXTRACT(EPOCH FROM (
                       COALESCE(base.completed, now()) - base.started
                   )) / 86400.0 AS days_taken,
                   COALESCE(tgt.target_days, 0) AS target_days,
                   (tgt.target_days IS NOT NULL
                    AND EXTRACT(EPOCH FROM (
                            COALESCE(base.completed, now()) - base.started
                        )) / 86400.0 > tgt.target_days) AS is_late,
                   base.company_id
              FROM (%s) AS base
              LEFT JOIN clearance_turnaround_target tgt
                     ON tgt.step = base.step
                    AND tgt.company_id = base.company_id
                    AND tgt.active = TRUE
        """ % select

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        # A view over other tables flushes nothing by itself; see CLAUDE.md.
        for model in ('logistics.file', 'logistics.expense',
                      'logistics.file.document', 'clearance.turnaround.target'):
            self.env[model].flush_model()
        return super()._search(domain, offset=offset, limit=limit,
                               order=order, **kwargs)

    def action_open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': ('logistics.file'
                          if self.res_model == 'logistics.file.document'
                          else self.res_model),
            'res_id': (self.file_id.id
                       if self.res_model == 'logistics.file.document'
                       else self.res_id),
            'view_mode': 'form',
            'target': 'current',
        }
