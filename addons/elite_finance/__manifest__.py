{
    'name': "Finance (Elimelec)",
    'summary': "The Finance app as Elimelec reads it: one Reports section, "
               "customer and vendor reports where the customers and vendors "
               "are, and the SYSCOHADA statements.",
    'description': """
Finance (Elimelec)
==================
Shapes Odoo Community's accounting app, renamed *Finance* by the Clearance
module, for the way Elimelec's finance team works (owner, 11/10/2026):

* **Reports** is a section of Finance. It holds the OCA accounting reports
  (general ledger, journal ledger, trial balance, open items, aged partner
  balance, VAT report), the financial statements built with MIS Builder,
  and Odoo's own analysis reports. Odoo's empty *Reporting* section is
  retired.
* **Customers** and **Vendors** carry their own reports: the ledger, the
  open items and the aged balance, each opening on receivable or payable
  accounts only.
* The two **SYSCOHADA statements** - *Compte de résultat* and *Bilan* -
  laid out by account class with MIS Builder, computed on screen, exported
  to PDF or Excel.

Every report previews on screen (the *View* button of the OCA wizards)
before it is exported.
    """,
    'author': "Elite Advisors",
    'website': "https://eliteadvisors.cm-ea.com",
    'category': 'Accounting/Accounting',
    'version': '19.0.5.0.0',
    'license': 'LGPL-3',
    'depends': ['account', 'account_financial_report', 'mis_builder'],
    'data': [
        'views/report_wizard_views.xml',
        'views/report_layouts.xml',
        'report/trial_balance_templates.xml',
        'views/finance_menus.xml',
        'data/mis_syscohada.xml',
    ],
    'assets': {
        # the report viewer: a report shown at once, filters on the page
        'web.assets_backend': [
            'elite_finance/static/src/report_viewer/**/*',
        ],
        # browser tests, loaded only when the server runs with --test-enable
        'web.assets_tests': [
            'elite_finance/static/tests/tours/**/*',
        ],
    },
    'post_init_hook': 'apply_finance_labels',
    'application': False,
    'installable': True,
}
