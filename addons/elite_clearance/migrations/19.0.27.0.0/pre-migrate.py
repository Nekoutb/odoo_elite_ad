"""Turnaround targets move from whole days to fractional hours.

Odoo would add `target_hours` empty and leave `target_days` behind, so
every configured allowance would silently become zero - and a zero target
marks every step late. The conversion is done here, before the new column
is loaded, and guarded: a database that never had the old column (a fresh
install) must not fail the upgrade.
"""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'clearance_turnaround_target'
           AND column_name = 'target_days'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        ALTER TABLE clearance_turnaround_target
          ADD COLUMN IF NOT EXISTS target_hours double precision
    """)
    cr.execute("""
        UPDATE clearance_turnaround_target
           SET target_hours = COALESCE(target_days, 0) * 24.0
         WHERE target_hours IS NULL
    """)
    cr.execute("""
        ALTER TABLE clearance_turnaround_target DROP COLUMN target_days
    """)
