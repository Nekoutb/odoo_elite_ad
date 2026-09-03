def migrate(cr, version):
    """Files already brought over by the legacy import were left In Progress,
    which claims work is ongoing on them. They are records: restate them as
    Imported so the status tells the truth."""
    cr.execute("""
        UPDATE logistics_file
           SET state = 'imported'
         WHERE legacy_id IS NOT NULL
           AND legacy_id <> 0
           AND state IN ('in_progress', 'done')
    """)
