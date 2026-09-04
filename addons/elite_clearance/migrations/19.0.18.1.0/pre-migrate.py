"""Convert logistics_billing_service.name from jsonb back to varchar.

The field was briefly translate=True, and Odoo stores a translated Char as
jsonb. Removing translate=True from the source does NOT convert an existing
column - Odoo leaves it as it found it - so a database created by the
earlier build still holds jsonb, and clearance.task cannot UNION it against
the varchar name columns of files and expenses. My Tasks dies with
"UNION types character varying and jsonb cannot be matched".

A fresh install has no such column and never saw the problem, which is
exactly why CI missed it: CI installs, production upgrades.
"""


def migrate(cr, version):
    cr.execute("""
        SELECT data_type
          FROM information_schema.columns
         WHERE table_name = 'logistics_billing_service'
           AND column_name = 'name'
    """)
    row = cr.fetchone()
    if not row or row[0] != 'jsonb':
        return                      # fresh install, or already converted

    # Keep the English text where there is one; otherwise whatever
    # translation the column happens to hold, so no name is lost.
    cr.execute("""
        ALTER TABLE logistics_billing_service
        ALTER COLUMN name TYPE varchar
        USING COALESCE(
            name ->> 'en_US',
            (SELECT value FROM jsonb_each_text(name) LIMIT 1)
        )
    """)
