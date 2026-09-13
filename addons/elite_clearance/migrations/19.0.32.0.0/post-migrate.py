"""Tell the existing invoices what they billed.

Billing became partial on 13/09/2026: a file is invoiced as costs land,
and a disbursement already recharged on an invoice that stands is never
offered again. What answers "already recharged?" is a pointer from the
disbursement to the invoice LINE - and on a database upgraded from an
earlier build that pointer is empty on every row, so every disbursement
on every billed file would look unbilled and could be charged twice.

The pointer is rebuilt from the line description, which billing itself
composes as "<category> — <description>": the match is exact by
construction, and a line is consumed once so two identical disbursements
on one file take one line each. Anything that does not match is left
unlinked and counted in the log rather than guessed at - an unmatched row
shows up as billable, which is visible, where a wrong link would not be.

The service lines are stamped with what they are at the same time, so a
second bill on an already-billed file does not propose the customs fee or
the commission again.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

COMMISSION = "Commission sur débours"
CUSTOMS_FEE = "Honoraires Agréés en Douane"


def _billable(expense):
    """What `_billable_expenses` meant before any of this existed."""
    if expense.is_legacy:
        return False
    return (expense.state == 'justified'
            or (expense.state == 'settled'
                and expense.payment_mode != 'advance'))


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    files = env['logistics.file'].with_context(active_test=False).search(
        [('invoice_id', '!=', False)])
    linked = unmatched = 0
    for file in files:
        # The disbursements sit on the unsplit invoice, or on the
        # disbursements half of a split bill.
        move = file.debours_invoice_id or file.invoice_id
        if not move or move.state == 'cancel':
            continue
        rows = list(move.invoice_line_ids.filtered(
            lambda line: line.clearance_category == 'debours'))
        for expense in file.expense_ids:
            if expense.billed_line_id or not _billable(expense):
                continue
            label = "%s — %s" % (expense.category_id.name,
                                 expense.description or "")
            match = next((row for row in rows if row.name == label), None)
            if match is None:
                unmatched += 1
                continue
            rows.remove(match)
            expense.billed_line_id = match.id
            linked += 1

    # Which service each standing service line is, read off its wording -
    # billing writes both labels itself, so this is reading back what it
    # wrote rather than guessing.
    services = env['account.move.line'].search([
        ('clearance_category', '=', 'prestation'),
        ('clearance_service_kind', '=', False),
    ])
    for line in services:
        name = line.name or ""
        if name.startswith(COMMISSION):
            line.clearance_service_kind = 'commission'
        elif name.startswith(CUSTOMS_FEE):
            line.clearance_service_kind = 'customs_fee'
        else:
            line.clearance_service_kind = 'other'

    _logger.info(
        "19.0.32.0.0: %s disbursement(s) linked to the invoice line that "
        "billed them, %s left unlinked and so billable again, %s service "
        "line(s) classified.", linked, unmatched, len(services))
