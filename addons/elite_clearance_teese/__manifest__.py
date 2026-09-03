{
    'name': "Clearance Files — Teese Legacy Import",
    'summary': "One-off migration of the Teese (TS Consulting) warehouse export "
               "into Clearance Files. Uninstall after go-live.",
    'description': """
Teese Legacy Import
===================
Loads the BMS warehouse export of Elimelec's legacy Teese system — six CSV
tables in one zip — into Clearance Files:

* partners (clients), suppliers, employees, ports, service types;
* dossiers → clearance files, with cargo, routing and provenance;
* avances de frais → legacy expenses (historical, never posted, never billed);
* invoices and their lines → draft customer invoices linked to their file,
  or posted on request;
* validation history → archived as an attachment on the import record.

Every row keeps its legacy identifier, so the import is idempotent: run it
again and it skips what is already there. The data never enters the code
repository — the zip is uploaded on the import record itself.

The judgement calls the mapping makes are written next to the code that
makes them, and in docs/legacy-migration-teese.md.
    """,
    'author': "Elite Advisors",
    'website': "https://eliteadvisors.cm-ea.com",
    'category': 'Services/Clearance',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['elite_clearance'],
    'data': [
        'security/ir.model.access.csv',
        'views/legacy_import_views.xml',
    ],
    'application': False,
    'installable': True,
}
