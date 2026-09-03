from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    logistics_file_id = fields.Many2one(
        'logistics.file', string="Clearance File", index=True, copy=False,
        help="The clearance file this invoice bills. A file may carry "
             "several invoices over its life (the legacy system did), so "
             "this is the link of record; logistics.file.invoice_id is the "
             "current one the workflow acts on.")

    # --- legacy (Teese) provenance -------------------------------------
    # An invoice issued by the legacy system, imported as a DRAFT customer
    # invoice so it shows in Invoicing and on its file with the billing
    # reference the client knows. It is record-keeping: the revenue and the
    # receivable it produced are in the trial balance uploaded at the cutoff
    # date, so posting it would count them twice. action_post refuses.
    is_legacy = fields.Boolean(
        string="Imported (Teese)", index=True, copy=False,
        help="Issued by the legacy system. Kept as a draft for the record; "
             "it can never be posted, because its revenue is already in the "
             "trial balance uploaded at the cutoff date.")
    legacy_id = fields.Integer(string="Legacy ID", index=True, copy=False)
    legacy_amount_untaxed = fields.Monetary(
        string="Teese Fee Base (HT)", copy=False, currency_field='currency_id',
        help="As exported from the legacy system.")
    legacy_amount_total = fields.Monetary(
        string="Teese Total (TTC)", copy=False, currency_field='currency_id',
        help="As exported from the legacy system. The draft's own total is "
             "built to match it line for line.")
    legacy_amount_residual = fields.Monetary(
        string="Outstanding at Export", copy=False, currency_field='currency_id',
        help="What the legacy system still showed as due when exported. "
             "Informational: the receivable itself is in the uploaded "
             "trial balance, not here.")
    legacy_payment_state = fields.Selection(
        [('not_paid', "Not Paid"), ('partial', "Partially Paid"), ('paid', "Paid")],
        string="Teese Payment State", copy=False)

    # ------------------------------------------------------------------
    # analytic: the file number on every line that reaches the ledger
    # ------------------------------------------------------------------
    def _clearance_analytic_distribution(self):
        """The file's analytic account as a distribution, or False."""
        self.ensure_one()
        account = self.logistics_file_id.analytic_account_id
        return {str(account.id): 100} if account else False

    def _clearance_stamp_analytic(self):
        """Tag every line of a clearance move with its file's analytic account.

        The owner's rule of 03/09/2026: everything clearance does that
        reaches the general ledger carries the file number - income,
        expense, asset and liability lines alike, including the receivable
        and the tax lines Odoo computes for itself.

        The consequence is deliberate and worth knowing: because every line
        of a balanced move is tagged, the analytic account's BALANCE nets to
        zero. It stops being a per-file profit figure and becomes a complete
        per-file journal - every posting on the file, in one place, whatever
        the account. Per-file margin comes from the file's own totals
        (out-of-pocket, commission, customs fee) or from an analytic report
        filtered by account type.

        Existing distributions are never overwritten: a line that already
        names an account keeps it.
        """
        for move in self:
            distribution = move._clearance_analytic_distribution()
            if not distribution:
                continue
            lines = move.line_ids.filtered(
                lambda line: not line.analytic_distribution
                and line.display_type not in ('line_section', 'line_note'))
            if lines:
                lines.analytic_distribution = distribution

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        # Stamped at creation so a draft shows the file on every line, and
        # again at posting for the lines Odoo adds on its own.
        moves._clearance_stamp_analytic()
        return moves

    def _post(self, soft=True):
        self._clearance_stamp_analytic()
        return super()._post(soft=soft)

    def action_post(self):
        legacy = self.filtered('is_legacy')
        if legacy:
            raise UserError(self.env._(
                "%s was issued by the legacy system and is kept as a draft "
                "for the record. Its revenue is in the trial balance "
                "uploaded at the cutoff date; posting it would count that "
                "revenue twice.", ", ".join(legacy.mapped('name'))))
        return super().action_post()
