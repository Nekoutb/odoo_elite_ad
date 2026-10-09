"""A bank journal as the owner wants every bank set up (09/10/2026).

A disbursement paid through a bank is credited to that journal's own
holding account - its Outstanding Payments account - and the bank account
moves only when the statement line is matched. A test bank journal needs
one, or paying through it is refused.
"""


def give_holding_account(journal):
    """Give `journal` a reconcilable Outstanding Payments account of its own."""
    env = journal.env
    account = env['account.account'].create({
        'code': 'H' + journal.code,
        'name': "%s - payments in transit" % journal.name,
        'account_type': 'asset_current',
        'reconcile': True,
    })
    lines = journal.outbound_payment_method_line_ids
    if not lines:
        lines = env['account.payment.method.line'].create({
            'journal_id': journal.id,
            'payment_method_id': env.ref(
                'account.account_payment_method_manual_out').id,
        })
    lines.payment_account_id = account.id
    return account
