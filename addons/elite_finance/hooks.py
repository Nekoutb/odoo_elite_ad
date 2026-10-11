"""Labels of the Finance menus, in every active language.

A data record writes the SOURCE language only (en_US); a translated field
keeps whatever the other languages already hold - "Rapports comptables
OCA" from OCA's own French file, for instance. So every label this module
sets or changes is written here, for each active language, from the
post-init hook and from the migration of any version that changes one.
"""

LABELS = {
    # renamed records of other modules
    'account_financial_report.menu_oca_reports': {
        'en_US': "Reports", 'fr_FR': "Rapports"},
    'mis_builder.mis_report_finance_menu': {
        'en_US': "Financial Statements", 'fr_FR': "États financiers"},
    # this module's own records
    'elite_finance.action_customer_ledger': {
        'en_US': "Customer Ledger", 'fr_FR': "Grand livre clients"},
    'elite_finance.menu_customer_ledger': {
        'en_US': "Customer Ledger", 'fr_FR': "Grand livre clients"},
    'elite_finance.action_customer_open_items': {
        'en_US': "Customer Open Items", 'fr_FR': "Écritures ouvertes clients"},
    'elite_finance.menu_customer_open_items': {
        'en_US': "Customer Open Items", 'fr_FR': "Écritures ouvertes clients"},
    'elite_finance.action_aged_receivables': {
        'en_US': "Aged Receivables", 'fr_FR': "Balance âgée clients"},
    'elite_finance.menu_aged_receivables': {
        'en_US': "Aged Receivables", 'fr_FR': "Balance âgée clients"},
    'elite_finance.action_vendor_ledger': {
        'en_US': "Vendor Ledger", 'fr_FR': "Grand livre fournisseurs"},
    'elite_finance.menu_vendor_ledger': {
        'en_US': "Vendor Ledger", 'fr_FR': "Grand livre fournisseurs"},
    'elite_finance.action_vendor_open_items': {
        'en_US': "Vendor Open Items", 'fr_FR': "Écritures ouvertes fournisseurs"},
    'elite_finance.menu_vendor_open_items': {
        'en_US': "Vendor Open Items", 'fr_FR': "Écritures ouvertes fournisseurs"},
    'elite_finance.action_aged_payables': {
        'en_US': "Aged Payables", 'fr_FR': "Balance âgée fournisseurs"},
    'elite_finance.menu_aged_payables': {
        'en_US': "Aged Payables", 'fr_FR': "Balance âgée fournisseurs"},
}


def apply_finance_labels(env):
    """Write every label of LABELS into each active language. A language
    LABELS does not know gets the English label, so nothing is left
    reading the old word. Idempotent."""
    active = set(env['res.lang'].search([('active', '=', True)]).mapped('code'))
    for xmlid, labels in LABELS.items():
        record = env.ref(xmlid, raise_if_not_found=False)
        if not record:
            continue
        record.update_field_translations('name', {
            code: labels.get(code, labels['en_US']) for code in active | {'en_US'}})
