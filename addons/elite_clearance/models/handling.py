# -*- coding: utf-8 -*-
"""Handling billed and due to the customer (owner's change brief,
20/10/2026).

Some files are billed with a Handling component. It is printed on the
customer's invoice, but it is NOT revenue and is never incurred: it is
due back to the customer and reduces what they owe. So instead of
crediting a revenue account or the débours account, the Handling line
is credited to the customer's own receivable account (or the Handling
account named in Settings), with the invoice's customer as partner, and
the credit is matched against the invoice's own receivable debit inside
the same entry: the open balance of the invoice is the total less the
Handling.

Only the `is_handling` flag counts. A billing component (an expense
category or a billable service) carries it; the invoice line copies it
at billing; a migrated line brings it from the load file. The
description is never read.
"""
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

HANDLING_LABEL = "Handling – dû au client"
HANDLING_SERVICE_NAME = "HAND — Handling (dû au client)"


def _migrating(env):
    return bool(env.context.get('clearance_migration'))


# =====================================================================
# Settings
# =====================================================================
class ResCompany(models.Model):
    _inherit = 'res.company'

    clearance_handling_account_id = fields.Many2one(
        'account.account', string="Handling Account",
        domain="[('deprecated', '=', False)]",
        help="Where a Handling line is credited, with the invoice's "
             "customer as partner. Empty = the customer's own receivable "
             "account (411100), matched against the invoice inside the "
             "same entry so the invoice's open balance is its total less "
             "the Handling.")
    # The last disbursement reference the old system issued, e.g.
    # FA26051022: FA, the year, the month, then a number that runs
    # through the year. The next disbursement keyed here takes the number
    # after it (owner, 20/10/2026).
    clearance_legacy_last_expense_ref = fields.Char(
        string="Last Legacy Disbursement Reference",
        help="The reference of the last disbursement keyed in the old "
             "system, e.g. FA26051022 - FA, the year, the month, then the "
             "running number of the year. The next disbursement keyed "
             "here takes the number after it, with its own month.")

    def _clearance_handling_account(self, partner):
        """The account a Handling line is credited to for `partner`."""
        self.ensure_one()
        if self.clearance_handling_account_id:
            return self.clearance_handling_account_id
        partner = partner.commercial_partner_id.with_company(self)
        return partner.property_account_receivable_id

    def write(self, vals):
        res = super().write(vals)
        if vals.get('clearance_legacy_last_expense_ref'):
            self._continue_legacy_expense_numbering()
        return res

    def _continue_legacy_expense_numbering(self):
        """Point the disbursement series at the number after the last one
        the old system issued.

        The reference is read, not trusted: FA, two digits of year, two
        of month, then the number; and no disbursement already keyed
        here in that year may hold a higher number, or the series would
        hand out a reference that is taken.
        """
        Expense = self.env['logistics.expense']
        for company in self:
            ref = (company.clearance_legacy_last_expense_ref or '').strip().upper()
            match = re.fullmatch(r'FA(\d{2})(\d{2})(\d{4,})', ref)
            if not match:
                raise UserError(self.env._(
                    "%(ref)s is not a disbursement reference. It reads as "
                    "FA, the year, the month and the number, e.g. %(example)s.",
                    ref=company.clearance_legacy_last_expense_ref,
                    example="FA26051022"))
            yy, last = match.group(1), int(match.group(3))
            if ref != company.clearance_legacy_last_expense_ref:
                super(ResCompany, company).write(
                    {'clearance_legacy_last_expense_ref': ref})
            year = 2000 + int(yy)
            taken = Expense.sudo().search([
                ('name', '=like', "FA%s%%" % yy),
                ('company_id', '=', company.id)])
            numbers = []
            for name in taken.mapped('name'):
                m = re.fullmatch(r'FA\d{4}(\d{4,})', name or '')
                if m:
                    numbers.append(int(m.group(1)))
            highest = max(numbers, default=0)
            if highest > last:
                raise UserError(self.env._(
                    "A disbursement numbered %(n)04d has already been keyed "
                    "here in %(year)s, so the series cannot go back to "
                    "%(ref)s. Key that number or a later one.",
                    n=highest, year=year, ref=ref))
            sequence = Expense._clearance_expense_sequence()
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


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    clearance_handling_account_id = fields.Many2one(
        related='company_id.clearance_handling_account_id', readonly=False)
    clearance_legacy_last_expense_ref = fields.Char(
        related='company_id.clearance_legacy_last_expense_ref', readonly=False)


# =====================================================================
# The billing components that carry the flag
# =====================================================================
class LogisticsExpenseCategory(models.Model):
    _inherit = 'logistics.expense.category'

    is_handling = fields.Boolean(
        string="Handling – due to customer",
        help="A Handling component: printed on the invoice, due back to "
             "the customer, credited to their receivable account. No "
             "disbursement can be keyed under it - nothing is ever paid "
             "for Handling.")


class LogisticsBillingService(models.Model):
    _inherit = 'logistics.billing.service'

    is_handling = fields.Boolean(
        string="Handling – due to customer", tracking=True,
        help="A Handling component: printed on the invoice, due back to "
             "the customer, credited to their receivable account (or the "
             "Handling account in Settings) with no VAT. The income "
             "account above is not used for it.")


class LogisticsExpense(models.Model):
    _inherit = 'logistics.expense'

    @api.constrains('category_id')
    def _check_not_handling_category(self):
        for expense in self:
            if expense.category_id.is_handling:
                raise ValidationError(self.env._(
                    "%s is a Handling component. Handling is billed to the "
                    "customer and due back to them; nothing is ever paid "
                    "for it, so no disbursement can be keyed under it.",
                    expense.category_id.display_name))

    @api.model
    def _clearance_expense_sequence(self):
        return self.env.ref('elite_clearance.seq_logistics_expense').sudo()


# The billing screen's service line carries the flag too (related to
# the component): it is declared in wizard/billing_wizard.py, because
# the wizard package loads after models and an _inherit here would find
# no such model in the registry (cost one CI cycle, 20/10/2026).


# =====================================================================
# The file: what it has billed as Handling
# =====================================================================
class LogisticsFile(models.Model):
    _inherit = 'logistics.file'

    handling_billed = fields.Monetary(
        string="Handling", compute='_compute_handling_billed',
        compute_sudo=True, currency_field='currency_id',
        help="Handling billed on this file and due back to the customer: "
             "the Handling lines of its posted invoices, credit notes "
             "deducted. Outside the débours result on both sides.")

    @api.depends('invoice_ids.state', 'invoice_ids.clearance_voided',
                 'invoice_ids.invoice_line_ids.price_subtotal',
                 'invoice_ids.invoice_line_ids.is_handling')
    def _compute_handling_billed(self):
        for file in self:
            total = 0.0
            moves = file.invoice_ids.sudo().filtered(
                lambda m: m.state == 'posted' and m._clearance_stands()
                and not m.is_legacy
                and m.move_type in ('out_invoice', 'out_refund'))
            for move in moves:
                sign = -1 if move.move_type == 'out_refund' else 1
                total += sign * sum(move.invoice_line_ids.filtered(
                    'is_handling').mapped('price_subtotal'))
            file.handling_billed = total


# =====================================================================
# The invoice: the Handling credit, matched inside the entry
# =====================================================================
class AccountMove(models.Model):
    _inherit = 'account.move'

    def _clearance_handling_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda l: l.is_handling and l.display_type == 'product')

    def _clearance_handling_check(self):
        """Refuse to post a Handling line that is not where it belongs:
        only the Handling account, the invoice's customer as partner, no
        VAT (brief, section 5)."""
        for move in self:
            lines = move._clearance_handling_lines()
            if not lines:
                continue
            expected = move.company_id._clearance_handling_account(move.partner_id)
            if not expected:
                raise UserError(self.env._(
                    "%(inv)s carries a Handling line but %(client)s has no "
                    "receivable account and no Handling account is set "
                    "under Clearance -> Configuration -> Settings.",
                    inv=move.display_name, client=move.partner_id.display_name))
            customer = move.partner_id.commercial_partner_id
            for line in lines:
                if line.account_id != expected:
                    raise UserError(self.env._(
                        "%(inv)s: the Handling line '%(line)s' is posted to "
                        "%(account)s. Handling is due back to the customer "
                        "and may only be credited to %(expected)s - never to "
                        "débours, revenue, VAT or the débours result.",
                        inv=move.display_name, line=line.name,
                        account=line.account_id.display_name,
                        expected=expected.display_name))
                if line.tax_ids:
                    raise UserError(self.env._(
                        "%(inv)s: the Handling line '%(line)s' carries VAT. "
                        "Handling is not revenue and carries no VAT.",
                        inv=move.display_name, line=line.name))
                if line.partner_id.commercial_partner_id != customer:
                    raise UserError(self.env._(
                        "%(inv)s: the Handling line '%(line)s' names %(who)s; "
                        "it must carry the invoice's customer, %(client)s.",
                        inv=move.display_name, line=line.name,
                        who=line.partner_id.display_name or "nobody",
                        client=customer.display_name))

    def _clearance_handling_label(self):
        """The ledger label of a Handling line: file | invoice | Handling.
        The printed wording is kept in clearance_print_name."""
        for move in self:
            for line in move._clearance_handling_lines():
                vals = {}
                if not line.clearance_print_name and line.name:
                    vals['clearance_print_name'] = line.name
                label = "%s | %s | %s" % (
                    move.logistics_file_id.name or "-", move.name or "-",
                    HANDLING_LABEL)
                if line.name != label:
                    vals['name'] = label
                if vals:
                    line.with_context(clearance_unlock=True).write(vals)

    def _clearance_handling_reconcile(self):
        """Match the Handling credit against the invoice's own receivable
        debit, inside the entry, so the open balance is the total less
        the Handling (brief 3.3). A negative Handling line (a correction)
        has swapped sides and is matched the same way. Only when the
        Handling account IS the receivable the invoice is carried on;
        a dedicated Handling account is cleared by the accountant."""
        for move in self:
            handling = move._clearance_handling_lines()
            if not handling:
                continue
            terms = move.line_ids.filtered(
                lambda l: l.display_type == 'payment_term')
            for line in handling:
                if line.reconciled or not line.account_id.reconcile:
                    continue
                partners = terms.filtered(
                    lambda t: t.account_id == line.account_id
                    and not t.reconciled
                    and ((t.balance > 0) != (line.balance > 0)))
                if not partners:
                    continue
                (line | partners).with_context(
                    no_exchange_difference=True).reconcile()
            # control 1 of the brief: open balance = total - Handling,
            # over the Handling that could be matched (a correction on a
            # document whose receivable debit runs the same way stays an
            # open item of its own on the customer)
            matched = handling.filtered('reconciled')
            if matched:
                handling_total = sum(matched.mapped('price_subtotal'))
                open_balance = move.amount_total - handling_total
                if move.currency_id.compare_amounts(
                        move.amount_residual, open_balance):
                    raise UserError(self.env._(
                        "%(inv)s: after matching the Handling, the open "
                        "balance reads %(residual)s and not %(expected)s "
                        "(total %(total)s less Handling %(handling)s).",
                        inv=move.display_name, residual=move.amount_residual,
                        expected=open_balance, total=move.amount_total,
                        handling=handling_total))

    def _post(self, soft=True):
        self._clearance_handling_check()
        posted = super()._post(soft=soft)
        with_handling = posted.filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund')
            and m._clearance_handling_lines())
        with_handling._clearance_handling_label()
        with_handling._clearance_handling_reconcile()
        return posted

    def _get_all_reconciled_invoice_partials(self):
        """The Handling match inside the entry is not a payment: keep it
        out of the 'Less Payment' widget and of everything else that
        lists what was reconciled against the invoice."""
        partials = super()._get_all_reconciled_invoice_partials()
        if not partials or not self._clearance_handling_lines():
            return partials
        own = set(self.line_ids.ids)
        return [p for p in partials if p['aml_id'] not in own]

    def _clearance_credit_line_vals(self, line):
        vals = super()._clearance_credit_line_vals(line)
        vals['is_handling'] = line.is_handling
        return vals


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # for the report: what is due to the customer on this line - a credit
    # is positive, a correction (debit) negative
    clearance_handling_amount = fields.Monetary(
        string="Handling Due", compute='_compute_clearance_handling_amount',
        store=True, currency_field='company_currency_id')
    clearance_file_id = fields.Many2one(
        related='move_id.logistics_file_id', string="Clearance File",
        store=True)
    clearance_invoice_payment_state = fields.Selection(
        related='move_id.payment_state', string="Invoice Payment")

    @api.depends('is_handling', 'balance')
    def _compute_clearance_handling_amount(self):
        for line in self:
            line.clearance_handling_amount = (
                -line.balance if line.is_handling else 0.0)

    @api.constrains('account_id', 'display_type', 'is_handling')
    def _check_payable_receivable(self):
        # A Handling line is a product line credited to the customer's
        # receivable (brief 1): Odoo's rule that only a payment-term line
        # may sit on a receivable account stands for every other line.
        return super(AccountMoveLine, self.filtered(
            lambda l: not l.is_handling))._check_payable_receivable()

    @api.constrains('is_handling', 'tax_ids')
    def _check_handling_no_tax(self):
        for line in self:
            if line.is_handling and line.tax_ids:
                raise ValidationError(self.env._(
                    "A Handling line carries no VAT: Handling is due back "
                    "to the customer, it is not revenue."))

    def write(self, vals):
        if 'is_handling' in vals and not _migrating(self.env):
            posted = self.filtered(lambda l: l.parent_state == 'posted'
                                   and l.is_handling != vals['is_handling'])
            if posted:
                raise UserError(self.env._(
                    "The Handling flag of a posted invoice line cannot be "
                    "changed (%s). Correct it with a credit note.",
                    ", ".join(posted.mapped('move_id.name'))))
        return super().write(vals)
