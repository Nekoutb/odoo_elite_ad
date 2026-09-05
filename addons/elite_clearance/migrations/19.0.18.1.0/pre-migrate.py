"""Convert logistics_billing_service.name from jsonb back to varchar.

The field was briefly translate=True, and Odoo stores a translated Char as
jsonb. Removing translate=True from the source does NOT convert an existing
column - Odoo leaves it as it found it - so a database created by the
earlier build still holds jsonb, and clearance.task cannot UNION it against
the varchar name columns of files and expenses. My Tasks dies with
"UNION types character varying and jsonb cannot be matched".

A fresh install has no such column and never saw the problem, which is
exactly why CI missed it: CI installs, production upgrades.


This script is deliberately BEST EFFORT. clearance.task now reads the
column whichever type it is, so tidying it is housekeeping, not the fix.
A failure here must never again take a deployment down with it: the last
attempt did exactly that and left staging serving the broken build for
eight hours.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    try:
        _convert(cr)
    except Exception:                                  # noqa: BLE001
        cr.rollback()
        _logger.warning(
            "Could not convert logistics_billing_service.name from jsonb to "
            "varchar. This is cosmetic - clearance.task reads the column "
            "either way - so the upgrade continues.", exc_info=True)


def _convert(cr):
    cr.execute("""
        SELECT data_type
          FROM information_schema.columns
         WHERE table_name = 'logistics_billing_service'
           AND column_name = 'name'
    """)
    row = cr.fetchone()
    if not row or row[0] != 'jsonb':
        return                      # fresh install, or already converted

    # Done in four steps rather than one ALTER ... USING, because
    # PostgreSQL forbids a subquery in a transform expression and the
    # fallback below needs one. An UPDATE has no such restriction.
    cr.execute("""
        ALTER TABLE logistics_billing_service
        ADD COLUMN name_varchar varchar
    """)
    # Keep the English text where there is one; otherwise whatever
    # translation the column happens to hold, so no name is lost.
    cr.execute("""
        UPDATE logistics_billing_service
           SET name_varchar = COALESCE(
                   name ->> 'en_US',
                   (SELECT value
                      FROM jsonb_each_text(name) AS translations(key, value)
                     LIMIT 1))
    """)
    cr.execute("ALTER TABLE logistics_billing_service DROP COLUMN name")
    cr.execute("""
        ALTER TABLE logistics_billing_service
        RENAME COLUMN name_varchar TO name
    """)
