import os

from odoo.tests import TransactionCase, tagged

# One whole transaction, built from the CTC-0063 sample: a file opened four
# days ago, thirteen disbursements, closed for operations and billed. It
# asserts the arithmetic and the elapsed time, and dumps the rendered
# invoice so the document itself can be looked at rather than described.

DEBOURS = [
    ("Retrait tardif", "Par dossier", 23850),
    ("RTC Acconage & relevage", "Par dossier", 1467524),
    ("Transport Dry MSC", "Par Conteneur", 220640),
    ("Surestaries", "Par dossier", 3094977),
    ("Transport ELIMELEC", "Par dossier", 250000),
    ("Code TEL Visite", "Par dossier", 17000),
    ("Frais Visite à domicile", "Par Conteneur", 100000),
    ("Frais remise RTC & PAD", "Par dossier", 134000),
    ("Levée delai de stockage", "Par dossier", 150000),
    ("Frais de reconduction BAD", "Par dossier", 23850),
    ("Assurance locale", "Par dossier", 28902),
    ("PAD", "Par dossier", 209285),
    ("Code additionnel EDA", "Par dossier", 52000),
]
DEBOURS_TOTAL = 5772028
HAD = 256974
OPENING_FEE = 20964


@tagged('post_install', '-at_install')
class TestInvoiceEndToEnd(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'E4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.income = Account.create({
            'code': 'E7062', 'name': "Honoraires", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales", 'type': 'sale', 'code': 'ESAL'})
        cls.vat = env['account.tax'].create({
            'name': "TVA 19.25", 'amount': 19.25, 'amount_type': 'percent',
            'type_tax_use': 'sale'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.income.id,
            'clearance_commission_account_id': cls.income.id,
            'clearance_service_fee_account_id': cls.income.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_service_tax_ids': [(6, 0, cls.vat.ids)],
            'vat': "M051612521065D",
            'company_registry': "RC/DLA/2018/B/2056",
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash", 'type': 'cash', 'code': 'ECSH'})
        cls.client = env['res.partner'].create({
            'name': "CAPITAL TRADING PRIVATE LIMITED", 'is_company': True,
            'street': "BP 18302 DOUALA - ZI MAGZI-BASSA, APRES VOLVO",
            'phone': "(+237) 691 149 100",
            'email': "info@capitaltrading-cm.com",
            'vat': "M071300046804A",
            'company_registry': "RC/LBE/2013/B/0560"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal", 'is_company': True, 'street': "BP 1234 Douala", 'email': "client@test.cm", 'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001", 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Douane", 'code': "E-DOU"})
        # commission at zero: this file is billed with an opening fee and
        # the customs fee, which is how the sample reads
        cls.service = env['logistics.service.type'].create({
            'name': "Import", 'code': "E-IM", 'commission_rate': 0.0})
        cls.usd = env.ref('base.USD')
        cls.usd.active = True

        bank_a = env['res.bank'].create({'name': "AFRILAND FIRST BANK"})
        bank_b = env['res.bank'].create({
            'name': "BANQUE GABONAISE ET FRANCAISE INTERNATIONALE (BGFI)"})
        Bank = env['res.partner.bank']
        cls.acc_a = Bank.create({
            'acc_number': "10005 00002 05987501001-50",
            'bank_id': bank_a.id, 'partner_id': company.partner_id.id})
        cls.acc_b = Bank.create({
            'acc_number': "10035 01110 40008467011-58",
            'bank_id': bank_b.id, 'partner_id': company.partner_id.id})
        company.clearance_invoice_bank_ids = [(6, 0, [cls.acc_a.id,
                                                      cls.acc_b.id])]

        # an approved billable service, proposed by Billing and signed off
        cls.opening = env['logistics.billing.service'].create({
            'name': "Frais d'ouverture de dossier",
            'unit_label': "Par dossier",
            'default_amount': OPENING_FEE, 'account_id': cls.income.id})
        cls.opening.action_approve()

    def _four_day_transaction(self):
        """Opened four days ago, worked, closed, billed."""
        env = self.env
        file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'partner_id': self.client.id,
            'service_type_id': self.service.id,
            'bl_awb_ref': "MEDUWA265794",
            'client_reference': "LAMINATE BLEACH-063",
            'supplier_name': "SHANDONG GHUNLONG",
            'goods_description': "LAMINATE,BOTTLE CAP,",
            'customs_declaration_ref': "2026IM0063",
            'container_count': 1, 'container_type': "40",
            'package_count': 865, 'weight_kg': 14367,
            'cargo_value': 284517.68,
            'cargo_value_currency_id': self.usd.id})
        file.state = 'in_progress'
        # the clock the Reporting section reads
        file.date_started = "2026-09-01 08:00:00"

        for description, unit, amount in DEBOURS:
            expense = env['logistics.expense'].create({
                'file_id': file.id, 'category_id': self.category.id,
                'description': description, 'amount': amount,
                'unit_label': unit})
            expense.action_submit()
            expense.action_approve()
            expense.write({'payment_mode': 'cash',
                           'journal_id': self.cash.id,
                           'vendor_id': self.vendor.id})
            expense.action_submit_settlement()
            expense.action_approve_settlement()
            expense.action_settle()

        file.action_close_operations()
        file.date_ops_closed = "2026-09-05 08:00:00"     # four days later

        wizard = env['logistics.billing.wizard'].with_context(
            active_id=file.id).create({})
        wizard.customs_fee_amount = HAD
        wizard.advance_had_amount = HAD
        wizard.advance_had_vat_amount = 49467
        wizard.service_line_ids = [(0, 0, {
            'service_id': self.opening.id,
            'name': self.opening.name,
            'unit_label': self.opening.unit_label,
            'amount': OPENING_FEE,
            'account_id': self.income.id})]
        wizard.action_create_invoice()
        return file

    # ------------------------------------------------------------------
    def test_01_the_thirteen_disbursements_are_billed_at_cost(self):
        file = self._four_day_transaction()
        invoice = file.invoice_id
        debours = invoice.invoice_line_ids.filtered(
            lambda l: l.clearance_category == 'debours')
        self.assertEqual(len(debours), 13)
        self.assertEqual(sum(debours.mapped('price_subtotal')), DEBOURS_TOTAL)
        self.assertFalse(debours.mapped('tax_ids'),
                         "a disbursement is the client's own liability")

    def test_02_the_services_are_the_fee_and_the_opening_charge(self):
        file = self._four_day_transaction()
        prestations = file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.clearance_category == 'prestation')
        self.assertEqual(sum(prestations.mapped('price_subtotal')),
                         HAD + OPENING_FEE)
        for line in prestations:
            self.assertEqual(line.tax_ids, self.vat,
                             "%s must carry VAT" % line.name)

    def test_03_the_totals_and_what_is_left_to_pay(self):
        file = self._four_day_transaction()
        invoice = file.invoice_id
        self.assertEqual(invoice.amount_untaxed,
                         DEBOURS_TOTAL + HAD + OPENING_FEE)
        self.assertAlmostEqual(invoice.amount_tax,
                               (HAD + OPENING_FEE) * 0.1925, places=2)
        # the client already advanced the customs fee and its VAT
        self.assertAlmostEqual(
            file.invoice_balance_due,
            invoice.amount_total - HAD - 49467, places=2)

    def test_04_the_file_took_four_days_to_close(self):
        file = self._four_day_transaction()
        row = self.env['clearance.turnaround'].search(
            [('file_id', '=', file.id), ('step', '=', 'file_ops_close')])
        self.assertTrue(row)
        self.assertTrue(row.is_done)
        self.assertAlmostEqual(row.days_taken, 4.0, places=1,
                               msg="opened 01/09, closed 05/09")

    def test_05_the_invoice_renders_and_is_dumped_for_inspection(self):
        """Renders the real document, and writes it out when asked.

        CLEARANCE_INVOICE_DUMP is set only by CI, so an ordinary run does
        nothing but assert.
        """
        file = self._four_day_transaction()
        rendered = self.env['ir.actions.report']._render_qweb_html(
            'elite_clearance.report_clearance_invoice',
            file.invoice_id.ids)[0]
        text = rendered.decode() if isinstance(rendered, bytes) else rendered
        for expected in ("Facture doit", "MEDUWA265794", "SHANDONG GHUNLONG",
                         "Surestaries", "Sous total", "TOTAL HT",
                         "AVANCE HAD/DAU", "RESTE",
                         "AFRILAND FIRST BANK", "Par Conteneur"):
            self.assertIn(expected, text, expected)

        destination = os.environ.get('CLEARANCE_INVOICE_DUMP')
        if destination:
            with open(destination, 'w', encoding='utf-8') as handle:
                handle.write(text)


@tagged('post_install', '-at_install')
class TestExpenseCapture(TransactionCase):
    """Capture in a dialog; run the workflow on the record's own page."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.client = env['res.partner'].create({
            'name': "Capture Client", 'is_company': True, 'street': "BP 1234 Douala", 'email': "client@test.cm", 'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001"})
        cls.category = env['logistics.expense.category'].create({
            'name': "Douane", 'code': "C-DOU"})
        cls.service = env['logistics.service.type'].create({
            'name': "Capture", 'code': "C-CAP", 'commission_rate': 2.0})
        cls.file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW000001",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': cls.client.id,
            'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'

    def _capture_view(self):
        return self.env.ref(
            'elite_clearance.logistics_expense_view_capture_form')

    def test_01_the_capture_form_carries_no_workflow_chrome(self):
        """The reason the inline row existed at all.

        The workflow form's eleven conditional header buttons crashed Owl
        when saved inside a one2many dialog. This form has none of it.
        """
        arch = self._capture_view().arch
        for forbidden in ("<header", "statusbar", "<chatter"):
            self.assertNotIn(forbidden, arch, forbidden)
        self.assertNotIn("action_submit", arch,
                         "no workflow button belongs in a dialog")

    def test_02_the_capture_form_asks_only_what_an_originator_keys(self):
        """What was spent, to whom, and the receipt. How it is paid -
        payment mode, journal, holder - is Finance's. The unit is not
        asked for at all: it is "Par dossier" for every disbursement.
        Owner spec 06/09/2026."""
        from lxml import etree
        arch = self._capture_view().arch
        for wanted in ('name="category_id"', 'name="description"',
                       'name="amount"', 'name="vendor_id"',
                       'name="attachment_ids"'):
            self.assertIn(wanted, arch, wanted)
        self.assertNotIn('name="unit_label"', arch, "the unit is fixed")
        self.assertNotIn('name="journal_id"', arch)
        self.assertIn('widget="clearance_expense_documents"', arch,
                      "the documents field is the drop-zone widget")
        # payment mode and holder appear only to feed the vendor's readonly
        # rule: invisible AND readonly, so the web client never sends them
        tree = etree.fromstring(arch)
        for helper in ('payment_mode', 'employee_id'):
            nodes = tree.xpath("//field[@name='%s']" % helper)
            self.assertTrue(nodes, helper)
            for node in nodes:
                self.assertEqual(node.get('invisible'), "1", helper)
                self.assertEqual(node.get('readonly'), "1", helper)

    def test_03_the_file_list_opens_the_capture_form_not_the_workflow_one(self):
        form = self.env.ref('elite_clearance.logistics_file_view_form')
        self.assertIn('logistics_expense_view_capture_form', form.arch,
                      "the dialog must be pointed at the capture form")
        self.assertNotIn('editable="bottom"', form.arch.split(
            'name="expense_ids"')[1].split('</field>')[0],
            "the inline row is gone")

    def test_04_a_captured_expense_appears_and_can_be_submitted(self):
        expense = self.env['logistics.expense'].create({
            'file_id': self.file.id,
            'category_id': self.category.id,
            'description': "Retrait tardif",
            'amount': 23850,
            'unit_label': "Par dossier"})
        self.assertIn(expense, self.file.expense_ids)
        self.assertEqual(expense.state, 'draft')
        expense.action_submit()
        self.assertEqual(expense.state, 'submitted',
                         "Submit is reachable straight from the row")

    def test_05_every_row_can_reach_its_own_page(self):
        expense = self.env['logistics.expense'].create({
            'file_id': self.file.id, 'category_id': self.category.id,
            'description': "Surestaries", 'amount': 3094977})
        action = expense.action_open_expense()
        self.assertEqual(action['res_model'], 'logistics.expense')
        self.assertEqual(action['res_id'], expense.id)
        self.assertEqual(action['view_mode'], 'form')
