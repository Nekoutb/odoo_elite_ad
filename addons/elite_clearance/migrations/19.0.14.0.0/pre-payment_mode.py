def migrate(cr, version):
    """'direct' splits into 'cash' and 'electronic'.

    The journal already says which it was, so nothing is guessed: a cash
    journal means cash, anything else means electronic. Legacy rows are
    emptied instead - the Teese export never carried a payment mode, and
    inventing one would be a claim about history nobody can support.
    """
    cr.execute("""
        UPDATE logistics_expense
           SET payment_mode = NULL
         WHERE payment_mode = 'direct' AND is_legacy = TRUE
    """)
    cr.execute("""
        UPDATE logistics_expense e
           SET payment_mode = CASE WHEN j.type = 'cash'
                                   THEN 'cash' ELSE 'electronic' END
          FROM account_journal j
         WHERE e.journal_id = j.id AND e.payment_mode = 'direct'
    """)
    cr.execute("""
        UPDATE logistics_expense
           SET payment_mode = 'electronic'
         WHERE payment_mode = 'direct'
    """)
