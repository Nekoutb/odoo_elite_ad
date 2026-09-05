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


    # ------------------------------------------------------------------
    # What the printed clearance invoice needs and Odoo will not give it.
    # ------------------------------------------------------------------
    def _get_name_invoice_report(self):
        """A clearance invoice prints Elimelec's own document.

        This is the hook Odoo's own localisations use to swap the invoice
        template. Anything without a clearance file keeps Odoo's standard
        report, so ordinary invoicing is untouched.
        """
        self.ensure_one()
        if self.logistics_file_id:
            return 'elite_clearance.report_clearance_invoice_document'
        return super()._get_name_invoice_report()

    def _clearance_amount_in_words(self, amount):
        """`CINQ MILLIONS ... XAF`, the way the document reads.

        Odoo's own amount_to_text follows the reader's language and appends
        the currency's UNIT LABEL ("Units", "Francs CFA"). This invoice is
        always French and always ends in the currency CODE, so the words
        are built here rather than borrowed.
        """
        self.ensure_one()
        currency = self.currency_id
        rounded = int(round(amount or 0.0))
        try:
            from num2words import num2words
            words = num2words(rounded, lang='fr')
        except (ImportError, NotImplementedError):
            # num2words is a hard dependency of Odoo 19, so this is the
            # belt to the braces: a figure is better than a blank line.
            words = "{:,}".format(rounded).replace(",", " ")
        return "%s %s" % (words.upper(), currency.name or "")

    def _clearance_money(self, amount):
        """A figure the way the document shows it: space-grouped, and to
        the currency's own precision rather than a hardcoded zero."""
        self.ensure_one()
        places = self.currency_id.decimal_places or 0
        text = "{:,.{p}f}".format(amount or 0.0, p=places)
        whole, _dot, fraction = text.partition(".")
        whole = whole.replace(",", " ")
        return "%s,%s" % (whole, fraction) if fraction else whole

    def _clearance_service_tax_label(self):
        """The VAT wording plus the rate actually charged, e.g.
        `TVA SUR PRESTATIONS (19,25%)`."""
        self.ensure_one()
        label = (self.company_id.clearance_invoice_vat_label
                 or "TVA SUR PRESTATIONS")
        taxes = self.invoice_line_ids.mapped('tax_ids').filtered(
            lambda t: t.amount_type == 'percent')
        if not taxes:
            return label
        rate = "{:.2f}".format(taxes[0].amount).rstrip('0').rstrip('.')
        return "%s (%s%%)" % (label, rate.replace('.', ','))

    def _clearance_invoice_banks(self):
        """The accounts the owner chose, in the order they chose them."""
        self.ensure_one()
        chosen = self.company_id.clearance_invoice_bank_ids
        if chosen:
            return chosen
        return self.company_id.partner_id.bank_ids[:2]


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    clearance_category = fields.Selection(
        [('debours', "Débours"), ('prestation', "Prestations")],
        string="Clearance Category", copy=False,
        help="Which block of the printed clearance invoice this line "
             "belongs under.")
    clearance_unit = fields.Char(
        string="Unit", copy=False,
        help="Printed as Unité, e.g. Par dossier or Par Conteneur.")
