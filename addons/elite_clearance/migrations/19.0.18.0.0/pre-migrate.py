"""`customs_regime` used to be free text filled by the Teese import; it is
now the closed IM4/IM5/IM7/IM8 list the owner specified. Move the old text
out of the way first, then keep only values that belong to the new list."""


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE logistics_file
        ADD COLUMN IF NOT EXISTS legacy_customs_regime varchar
    """)
    cr.execute("""
        UPDATE logistics_file
           SET legacy_customs_regime = customs_regime
         WHERE customs_regime IS NOT NULL
           AND legacy_customs_regime IS NULL
    """)
    # 'IM4' and 'im4' both mean the same regime; anything else (EX1, EX2,
    # free text) is history and is left only in legacy_customs_regime.
    cr.execute("""
        UPDATE logistics_file
           SET customs_regime = lower(customs_regime)
         WHERE lower(customs_regime) IN ('im4', 'im5', 'im7', 'im8')
    """)
    cr.execute("""
        UPDATE logistics_file
           SET customs_regime = NULL
         WHERE customs_regime IS NOT NULL
           AND customs_regime NOT IN ('im4', 'im5', 'im7', 'im8')
    """)
