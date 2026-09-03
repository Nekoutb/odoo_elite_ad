def migrate(cr, version):
    """payment_mode used to default to 'direct' at keying. It is now blank
    until Finance sets it, so an expense still in draft or submitted must
    not carry a mode nobody chose. Anything approved or beyond keeps what
    it has: Finance had already acted on it."""
    cr.execute("""
        UPDATE logistics_expense
           SET payment_mode = NULL
         WHERE state IN ('draft', 'submitted')
    """)
