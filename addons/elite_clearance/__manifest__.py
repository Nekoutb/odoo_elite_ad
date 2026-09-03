{
    'name': "Clearance Files",
    'summary': "Customs clearance job files: document gate, out-of-pocket "
               "disbursements, cash advances and client recharge billing",
    'description': """
Clearance Files
===============
Runs a customs clearance business end to end, one job file at a time.

**The file** (`logistics.file`) — draft → in progress → closed for operations
→ complete. Each file owns an analytic account, so every cost and every
revenue line posted against it is tagged and per-file profitability falls out
of the accounting rather than out of a spreadsheet.

**The document gate** — a checklist generated from the service type. Work
cannot start while a mandatory document is missing, unless an approver signs
a written waiver, which is posted to the file's audit trail. Reception stamps
one shared transaction timestamp for everything saved together.

**Out-of-pocket disbursements** (`logistics.expense`) — draft → submitted →
approved → settled, and for advances a further justification step that
requires supporting documents. Direct settlements debit 47xx Débours
engagés. An advance instead debits 421101 Personnel débours avancés against
the staff member as auxiliary — it is their debt, not the client's — and only
the justification entry reclassifies it to 47xx, which is what makes it
billable. A file carrying an unjustified advance cannot be billed unless an
Operations Manager waives it in writing; the waiver releases the file, never
the money, which stays on 421101 to recover from the holder.

**Billing** — the client invoice recharges disbursements at cost against the
out-of-pocket account (clearing it) and adds the fee lines: a commission
computed from the service type's rate, plus the manually keyed customs
service fee. A file cannot be marked complete until that invoice is posted,
and reopening a closed file needs a manager and a written reason.

Approval rights are configurable per company under Settings → Clearance;
where no explicit approver list is set, the security groups apply.
    """,
    'author': "Elite Advisors",
    'website': "https://eliteadvisors.cm-ea.com",
    'category': 'Services/Clearance',
    'version': '19.0.14.0.0',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'analytic', 'account', 'hr'],
    'data': [
        # security first: groups and model access must exist before the
        # records and views that reference them are loaded.
        'security/clearance_security.xml',
        'security/ir.model.access.csv',
        'security/clearance_record_rules.xml',
        # master data
        'data/ir_sequence_data.xml',
        'data/analytic_plan_data.xml',
        # Wizards before logistics_file_views.xml: the file's header buttons
        # resolve %(action_...)d at load time, so those actions must already
        # exist. Menus last, for the same reason.
        'wizard/document_date_wizard_views.xml',
        'wizard/reopen_wizard_views.xml',
        'views/logistics_port_views.xml',
        'views/logistics_document_type_views.xml',
        'views/logistics_service_type_views.xml',
        'views/logistics_expense_views.xml',
        'views/logistics_file_views.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
        'views/clearance_menus.xml',
    ],
    'demo': [
        'demo/clearance_demo.xml',
    ],
    'post_init_hook': 'seed_clearance_master_data',
    'application': True,
    'installable': True,
}
