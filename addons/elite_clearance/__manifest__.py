{
    'name': "Clearance Files",
    'summary': "Customs clearance job files with a service-type document checklist and a waiver gate",
    'description': """
Clearance Files — step 1
========================
Creates the clearance job file as a first-class object:

* a document checklist generated from the service type;
* a hard gate preventing work from starting while mandatory documents are missing,
  unless a manager approves a documented waiver;
* an analytic account per file, so every later cost and revenue can be tagged to it.

Out-of-pocket expenses, disbursement approvals, cash advances and billing are
deliberately NOT in this version. See the build roadmap.
    """,
    'author': "Elite Advisors",
    'website': "https://eliteadvisors.cm-ea.com",
    'category': 'Services/Clearance',
    'version': '19.0.3.0.0',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'analytic', 'account', 'hr'],
    'data': [
        'security/clearance_security.xml',
        'security/ir.model.access.csv',
        'data/analytic_plan_data.xml',
        'data/ir_sequence_data.xml',
        'data/expense_data.xml',
        'views/logistics_document_type_views.xml',
        'views/logistics_service_type_views.xml',
        'views/document_date_wizard_views.xml',
        'views/logistics_expense_views.xml',
        'views/logistics_file_views.xml',
        'views/clearance_menus.xml',
    ],
    'demo': [
        'demo/clearance_demo.xml',
    ],
    'post_init_hook': 'seed_clearance_master_data',
    'application': True,
    'installable': True,
}
