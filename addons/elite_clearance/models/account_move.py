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
    # Which part of a clearance bill this invoice is. An unsplit bill
    # carries everything ('full'); a split bill (owner 07/09/2026) issues
    # one 'debours' invoice - the out-of-pocket expenses, no VAT - and one
    # 'services' invoice for the commission and fees, with VAT. The printed
    # document reads it to leave out the rows that do not apply.
    clearance_invoice_kind = fields.Selection(
        [('full', "Disbursements and services"),
         ('debours', "Disbursements only"),
         ('services', "Services only")],
        string="Clearance Invoice Kind", copy=False, readonly=True)

    # ------------------------------------------------------------------
    # Cancelling and crediting a clearance invoice (owner spec 13/09/2026)
    # ------------------------------------------------------------------
    # A POSTED invoice is never unposted and never deleted: the entry it
    # made is the record of what the client was told, and the ledger keeps
    # it. Cancelling it therefore means raising the same entry with the
    # signs the other way round - and once that is done the invoice no
    # longer stands, even though it is still posted. This flag is what "no
    # longer stands" means to everything in the module that asks whether a
    # file is billed.
    clearance_voided = fields.Boolean(
        string="Voided", copy=False, readonly=True,
        help="Cancelled by Billing: the mirror entry has been raised. The "
             "invoice itself stays posted, because a posted entry is not "
             "unmade, but the client owes nothing on it.")
    clearance_void_reason = fields.Text(
        string="Why it was cancelled", copy=False, readonly=True)
    clearance_voided_by_id = fields.Many2one(
        'res.users', string="Cancelled By", copy=False, readonly=True)
    clearance_void_date = fields.Datetime(
        string="Cancelled On", copy=False, readonly=True)
    clearance_credit_reason = fields.Text(
        string="Why this credit note was issued", copy=False, readonly=True,
        help="On the credit note itself: what the billing agent gave as "
             "the reason before a single line was reversed.")

    @api.ondelete(at_uninstall=False)
    def _clearance_keep_billed_invoices(self):
        """A file's invoice is cancelled, never deleted.

        The file names one invoice, or the two halves of a split bill, and
        every gate - billed? posted? which half is missing? - reads those
        pointers. Deleting one would leave the survivor reading as the
        whole bill. The foreign key refuses it anyway; this says why.
        """
        files = self.env['logistics.file'].sudo().search(
            ['|', ('invoice_id', 'in', self.ids),
             ('debours_invoice_id', 'in', self.ids)])
        if files:
            raise UserError(self.env._(
                "%(inv)s is the invoice of clearance file %(file)s. Cancel "
                "it if it should not stand - the file keeps it as the "
                "record of what was billed.",
                inv=", ".join(self.filtered(
                    lambda m: m in files.invoice_id | files.debours_invoice_id
                ).mapped('name')),
                file=", ".join(files.mapped('name'))))

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
        if self.logistics_file_id and self.move_type == 'out_invoice':
            return 'elite_clearance.report_clearance_invoice_document'
        return super()._get_name_invoice_report()

    def _clearance_report_lang(self):
        """French for formatting - but only if French is installed.

        res.lang holds only the languages actually installed, and Odoo
        raises "Invalid language code" the moment a t-field formats against
        one that is missing. Forcing fr_FR therefore took the whole report
        down on any database without it. The document's wording is
        hardcoded French regardless; this decides number and date
        formatting only, so falling back costs almost nothing and keeps
        the invoice printable.
        """
        self.ensure_one()
        codes = self.env['res.lang'].sudo().search([]).mapped('code')
        if 'fr_FR' in codes:
            return 'fr_FR'
        for code in codes:
            if code.startswith('fr'):
                return code
        return self.env.context.get('lang') or 'en_US'

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

    def _clearance_advances(self):
        """The client's advances this invoice deducts: (HAD/DAU, VAT on
        HAD/DAU, other), each None when the row does not belong on it.

        An advance on the HAD/DAU - and the VAT on it - is an advance on the
        SERVICES; "other advances" are funds the client put up for the
        disbursements. An unsplit invoice deducts all four, rows printed
        even at zero as the model document does; a split invoice deducts
        its own side's and omits the other rows.

        The fourth is different in kind from the first three: those are
        figures the biller types on the face of the document, while this
        one is the sum of receipts actually posted against the client's
        account for this file (owner spec 15/09/2026). It follows "other
        advances" to the disbursements side of a split bill, because that
        is what a client puts money up for. It prints only when there is
        one, so an invoice for a client who has paid nothing in advance
        reads exactly as it did before.
        """
        self.ensure_one()
        file = self.logistics_file_id
        kind = self.clearance_invoice_kind or 'full'
        received = file.client_advance_total
        return (
            file.advance_had_amount if kind != 'debours' else None,
            file.advance_had_vat_amount if kind != 'debours' else None,
            file.advance_other_amount if kind != 'services' else None,
            received if (received and kind != 'services') else None,
        )

    def _clearance_advance_total(self):
        self.ensure_one()
        return sum(amount for amount in self._clearance_advances() if amount)

    def _clearance_prints_vat(self):
        """A disbursements-only invoice carries no VAT and shows no VAT
        row; every other clearance invoice shows it, at zero if need be."""
        self.ensure_one()
        return (self.clearance_invoice_kind or 'full') != 'debours'

    # ------------------------------------------------------------------
    # Cancelling and crediting (owner spec 13/09/2026)
    # ------------------------------------------------------------------
    def _clearance_stands(self):
        """Is this still a bill the client owes?

        Draft or posted, and not voided. Everything that asks "is the file
        billed?", "is there anything left to bill?" or "is this
        disbursement already recharged?" comes through here, so there is
        one answer and not four.
        """
        self.ensure_one()
        return self.state != 'cancel' and not self.clearance_voided

    def _clearance_credit_note_name(self):
        """AV26IM0001 - credit notes have their own series, per service
        type, so a credit note is never mistaken for an invoice."""
        self.ensure_one()
        file = self.logistics_file_id
        if not file:
            return False
        return self.env['logistics.file']._next_reference(
            'credit', file.service_type_id, self.company_id)

    def _clearance_adjustment_account(self, amount):
        """Where the share of a recharge adjustment goes when one
        disbursement line is credited on its own."""
        self.ensure_one()
        existing = self.invoice_line_ids.filtered(
            lambda line: line.clearance_category == 'adjustment')
        if existing:
            return existing[0].account_id
        company = self.company_id
        account = (company.clearance_oop_overcharge_account_id if amount > 0
                   else company.clearance_oop_undercharge_account_id)
        if not account:
            raise UserError(self.env._(
                "Configure the disbursement over/undercharge accounts under "
                "Clearance - Configuration - Settings before crediting a "
                "line that was recharged at other than cost."))
        return account

    def _clearance_creditable_lines(self, standing_only=False):
        """The lines a credit note may reverse.

        The product lines, and never the aggregate recharge adjustment:
        that line carries the difference between what the disbursements
        cost and what the client was charged, is printed nowhere, and on
        its own means nothing to anybody. It is reversed through the lines
        it belongs to instead - each takes its own share with it, and the
        shares add back to the aggregate exactly.
        """
        self.ensure_one()
        lines = self.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product'
            and line.clearance_category != 'adjustment')
        if standing_only:
            lines = lines.filtered(lambda line: not line.clearance_credited)
        return lines

    def _clearance_credit_line_vals(self, line):
        """One line of the credit note, mirroring one line of the invoice."""
        return {
            'name': line.name,
            'quantity': line.quantity,
            'price_unit': line.price_unit,
            'discount': line.discount,
            'product_id': line.product_id.id or False,
            'account_id': line.account_id.id,
            'tax_ids': [fields.Command.set(line.tax_ids.ids)],
            'analytic_distribution': line.analytic_distribution,
            'clearance_category': line.clearance_category,
            'clearance_unit': line.clearance_unit,
            'clearance_service_kind': line.clearance_service_kind,
            # The share of the recharge adjustment is a posting of its own,
            # added beside this line, so the copy carries none of it.
            'clearance_adjustment': 0.0,
        }

    def _clearance_ensure_storno(self):
        """A reversal is NEGATED, not swapped - assert it here, every time.

        The owner's rule of 13/09/2026: a cancellation shows the original
        columns with a minus sign rather than debiting what was credited.
        In Odoo that is one company switch, storno accounting, and there is
        no per-invoice way to do it: `debit` and `credit` are computed from
        `balance` alone, and the receivable line of the credit note is
        generated by Odoo rather than passed by us, so a flag set on the
        lines we build would miss it.

        The switch is a STORED COMPUTE over the company's fiscal country.
        Loading a chart of accounts sets that country and silently turns
        the switch back off - and the next cancellation would then be
        booked the other way round with nobody told. So it is asserted at
        the moment it decides something, rather than trusted to have
        stayed where it was put. Idempotent, and said out loud in the
        chatter on the one occasion it has to act.
        """
        self.ensure_one()
        company = self.company_id
        if company.account_storno:
            return
        company.sudo().account_storno = True
        self.message_post(body=self.env._(
            "Storno accounting was switched back on for %s, so this "
            "reversal books the original entry negated, in the same "
            "columns, rather than the other way round. It had been turned "
            "off - loading a chart of accounts does that by itself.",
            company.display_name))

    def _clearance_raise_credit_note(self, lines, reason):
        """Raise the reversing entry for `lines`, post it, and match it off.

        The owner's rule of 13/09/2026: cancelling an invoice books the
        original entry again with the signs the other way round - debit
        what was credited, credit what was debited, for the same amounts.
        A customer credit note carrying the same lines produces exactly
        that, so the credit note IS the reversing entry rather than a
        document standing beside one. It is posted straight away: an
        unposted reversal reverses nothing. "The signs the other way
        round" means NEGATED and not swapped - the revenue stays in the
        credit column at minus the original figure - which is storno
        accounting; see _clearance_ensure_storno.

        Each line brings its share of the recharge adjustment with it.
        The aggregate adjustment line is never reversed directly and is
        never offered for selection: on its own it means nothing to
        anybody, and the shares add back to it exactly.
        """
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(self.env._(
                "%s is not posted, so there is no entry to reverse.",
                self.name))
        if not lines:
            raise UserError(self.env._(
                "Choose at least one line to credit on %s.", self.name))
        self._clearance_ensure_storno()
        commands = []
        for line in lines:
            commands.append(fields.Command.create(
                self._clearance_credit_line_vals(line)))
            share = line.clearance_adjustment
            if share and line.clearance_category == 'debours':
                commands.append(fields.Command.create({
                    'name': self.env._("Ajustement sur débours - %s", line.name),
                    'quantity': 1.0,
                    'price_unit': share,
                    'account_id': self._clearance_adjustment_account(share).id,
                    'tax_ids': [fields.Command.clear()],
                    'clearance_category': 'adjustment',
                    'analytic_distribution': line.analytic_distribution,
                }))
        credit = self.env['account.move'].create({
            'move_type': 'out_refund',
            'journal_id': self.journal_id.id,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': fields.Date.context_today(self),
            'logistics_file_id': self.logistics_file_id.id,
            'clearance_invoice_kind': self.clearance_invoice_kind,
            'clearance_credit_reason': reason,
            'reversed_entry_id': self.id,
            'invoice_origin': self.name,
            'ref': self.env._("Reversal of %s", self.name),
            'name': self._clearance_credit_note_name() or '/',
            'invoice_line_ids': commands,
        })
        credit.action_post()
        self._clearance_match_credit_note(credit)
        return credit

    def _clearance_match_credit_note(self, credit):
        """Set the credit note against the invoice, so the receivable shows
        what is really still due rather than both documents in full."""
        self.ensure_one()
        lines = (self | credit).line_ids.filtered(
            lambda line: line.display_type == 'payment_term'
            and not line.reconciled and line.account_id.reconcile)
        if len(lines) > 1 and len(lines.mapped('account_id')) == 1:
            lines.reconcile()


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    clearance_category = fields.Selection(
        [('debours', "Débours"), ('prestation', "Prestations"),
         ('adjustment', "Recharge adjustment")],
        string="Clearance Category", copy=False,
        help="Which block of the printed clearance invoice this line "
             "belongs under. An 'adjustment' line is accounting only: it "
             "carries the difference between what a disbursement cost and "
             "what the client is charged, and is NOT printed.")
    clearance_adjustment = fields.Monetary(
        string="Recharge Adjustment", copy=False,
        help="The difference between what this disbursement cost and what "
             "the client is charged for it. The line posts AT COST so the "
             "out-of-pocket account clears in full, and the invoice prints "
             "the two added together - so correcting the line moves the "
             "printed figure with it. Zero means charged at cost.")
    clearance_unit = fields.Char(
        string="Unit", copy=False,
        help="Printed as Unité, e.g. Par dossier or Par Conteneur.")
    # A line that has been credit-noted is spent: the disbursement behind
    # it is billable again, and the service on it may be charged again.
    # The credit note is the record of the reversal; this is what the rest
    # of the module reads, because it answers per LINE and a credit note
    # may cover only some of them.
    clearance_credited = fields.Boolean(
        string="Credited", copy=False, readonly=True,
        help="This line has been reversed by a credit note. What it "
             "billed can be billed again.")
    clearance_service_kind = fields.Selection(
        [('commission', "Commission on disbursements"),
         ('customs_fee', "Honoraires Agréés en Douane"),
         ('file_fee', "Frais de dossier"),
         ('other', "Other billable service")],
        string="Clearance Service", copy=False,
        help="Which standing service line this is, so the billing screen "
             "knows what has already been charged on an earlier invoice "
             "and does not propose it twice.")
