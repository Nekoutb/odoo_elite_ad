"""Who collects the cash (owner, 13/10/2026).

A disbursement now names the member of staff who comes to the till for
the money - the requester unless they said otherwise. Rows keyed under
the previous build have nobody named, so the ones not yet paid out get
their requester, which is what the requester would have been offered.
Rows already paid keep no name: the voucher printed for them carries
none, and a name written afterwards would claim to know who collected
cash that has already gone.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE logistics_expense e
           SET collector_id = emp.id
          FROM hr_employee emp
         WHERE e.collector_id IS NULL
           AND emp.user_id = e.create_uid
           AND emp.company_id = e.company_id
           AND e.state IN ('draft', 'submitted', 'approved',
                           'settlement_submitted', 'settlement_approved')
    """)
