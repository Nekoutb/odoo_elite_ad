def migrate(cr, version):
    """'direct' splits into 'cash' and 'electronic'.

    The journal already says which it was, so nothing is guessed: a cash
    journal means cash, anything else means electronic. Legacy rows are
    emptied instead - the Teese export never carried a payment mode, and
    inventing one would be a claim about history nobody can support.
    """
    # is_legacy arrived after this version, so a database upgrading from
    # far enough back does not have the column yet at PRE time - the new
    # field definitions have not been applied. Skip that clause rather
    # than assume: without the column there are no legacy rows either.
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'logistics_expense'
           AND column_name = 'is_legacy'
    """)
    if cr.fetchone():
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
