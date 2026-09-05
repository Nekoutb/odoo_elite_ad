from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestClearanceInvoicePrint(TransactionCase):
    """The printed invoice is the document the client already receives."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'P4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.income = Account.create({
            'code': 'P7062', 'name': "Fees", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales", 'type': 'sale', 'code': 'PSAL'})
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
            'name': "Cash", 'type': 'cash', 'code': 'PCSH'})
        cls.client = env['res.partner'].create({
            'name': "CAPITAL TRADING PRIVATE LIMITED", 'is_company': True,
            'street': "BP 18302 DOUALA", 'phone': "(+237) 691 149 100",
            'email': "info@capitaltrading-cm.com",
            'vat': "M071300046804A",
            'company_registry': "RC/LBE/2013/B/0560"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal P", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port", 'code': "P-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Print test", 'code': "P-PRN", 'commission_rate': 2.0})

        # two bank accounts on the company, so the block has something to show
        bank_a = env['res.bank'].create({'name': "AFRILAND FIRST BANK"})
        bank_b = env['res.bank'].create({'name': "BGFI"})
        Bank = env['res.partner.bank']
        cls.acc_a = Bank.create({
            'acc_number': "10005 00002 05987501001-50",
            'bank_id': bank_a.id, 'partner_id': company.partner_id.id})
        cls.acc_b = Bank.create({
            'acc_number': "10035 01110 40008467011-58",
            'bank_id': bank_b.id, 'partner_id': company.partner_id.id})

    def _billed_file(self, amount=566899, quantity=None):
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'partner_id': self.client.id,
            'service_type_id': self.service.id,
            'bl_awb_ref': "MEDUWA265794",
            'client_reference': "LAMINATE BLEACH-063",
            'supplier_name': "SHANDONG GHUNLONG",
            'goods_description': "LAMINATE,BOTTLE CAP,",
            'container_count': 1, 'container_type': "40",
            'package_count': 865, 'weight_kg': 14367})
        file.state = 'in_progress'
        expense = self.env['logistics.expense'].create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Retrait tardif", 'amount': amount,
            'unit_label': "Par dossier"})
        expense.action_submit()
        expense.action_approve()
        expense.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                       'vendor_id': self.vendor.id})
        expense.action_submit_settlement()
        expense.action_approve_settlement()
        expense.action_settle()
        file.action_close_operations()
        wizard = self.env['logistics.billing.wizard'].with_context(
            active_id=file.id).create({})
        wizard.customs_fee_amount = 256974
        wizard.action_create_invoice()
        if quantity is not None:
            line = file.invoice_id.invoice_line_ids.filtered(
                lambda l: l.clearance_category == 'debours')[0]
            line.quantity = quantity
        return file

    def _html(self, invoice):
        rendered = self.env['ir.actions.report']._render_qweb_html(
            'elite_clearance.report_clearance_invoice', invoice.ids)[0]
        return rendered.decode() if isinstance(rendered, bytes) else rendered

    # --- the page ------------------------------------------------------
    def test_01_every_label_from_the_document_is_present(self):
        file = self._billed_file()
        text = self._html(file.invoice_id)
        for label in ("Facture doit N°", "N° BL/N° LTA", "Reference",
                      "N° Dossier", "Fournisseur", "Produits", "Valeur RVC",
                      "NBRE TC", "Type de TC", "POIDS (KG)", "NBRE DE COLIS",
                      "Catégorie", "Désignation", "Unité", "Quantité",
                      "Prix unitaire", "Montant", "Sous total",
                      "TOTAL HT", "TOTAL TTC", "AVANCE HAD/DAU",
                      "AVANCE TVA/HAD DAU", "AUTRES AVANCES", "RESTE",
                      "Arrêté la présente facture au montant de",
                      "BANK :", "ACCOUNT NAME :", "ACCOUNT N° :",
                      "PAYMENT CONDITIONS :"):
            self.assertIn(label, text, label)

    def test_02_the_shipment_and_the_client_are_printed(self):
        file = self._billed_file()
        text = self._html(file.invoice_id)
        for value in ("MEDUWA265794", "LAMINATE BLEACH-063",
                      "SHANDONG GHUNLONG", "LAMINATE,BOTTLE CAP,",
                      "CAPITAL TRADING PRIVATE LIMITED",
                      "M071300046804A", "RC/LBE/2013/B/0560",
                      "M051612521065D", "RC/DLA/2018/B/2056"):
            self.assertIn(value, text, value)

    def test_03_the_amount_in_words_is_french_and_ends_in_the_code(self):
        file = self._billed_file()
        words = file.invoice_id._clearance_amount_in_words(5797029)
        self.assertTrue(words.endswith("XAF"), words)
        self.assertIn("MILLIONS", words, words)
        self.assertEqual(words, words.upper(), "the document shouts it")
        self.assertNotIn("MILLION ", words.replace("MILLIONS", ""),
                         "French, not English")

    def test_04_the_vat_row_carries_the_rate(self):
        file = self._billed_file()
        label = file.invoice_id._clearance_service_tax_label()
        self.assertEqual(label, "TVA SUR PRESTATIONS (19,25%)")
        self.assertIn(label, self._html(file.invoice_id))

    def test_05_the_vat_wording_is_configurable(self):
        self.env.company.clearance_invoice_vat_label = "TVA"
        file = self._billed_file()
        self.assertEqual(file.invoice_id._clearance_service_tax_label(),
                         "TVA (19,25%)")

    def test_06_the_title_and_the_complaints_window_are_configurable(self):
        self.env.company.write({
            'clearance_invoice_title': "FACTURE N°",
            'clearance_invoice_complaint_days': 30,
            'clearance_invoice_payment_terms': "30 jours fin de mois"})
        file = self._billed_file()
        text = self._html(file.invoice_id)
        self.assertIn("FACTURE N°", text)
        self.assertIn("30 days", text)
        self.assertIn("30 jours fin de mois", text)

    def test_07_amounts_are_grouped_and_whole_in_xaf(self):
        file = self._billed_file()
        self.assertEqual(file.invoice_id._clearance_money(6049966),
                         "6 049 966")
        self.assertEqual(file.invoice_id._clearance_money(53504), "53 504")

    def test_08_a_large_quantity_is_not_printed_in_scientific_notation(self):
        file = self._billed_file(quantity=1000000)
        text = self._html(file.invoice_id)
        self.assertNotIn("1e+06", text)
        self.assertIn("1 000 000", text)

    def test_09_the_debours_subtotal_counts_its_lines(self):
        """The document shows the count on débours and not on services."""
        file = self._billed_file()
        text = self._html(file.invoice_id)
        self.assertIn("Sous total", text)
        self.assertIn("Debours", text)
        self.assertIn("Prestations", text)

    def test_10_the_configured_banks_print_in_order(self):
        self.env.company.clearance_invoice_bank_ids = [
            (6, 0, [self.acc_b.id, self.acc_a.id])]
        file = self._billed_file()
        banks = file.invoice_id._clearance_invoice_banks()
        self.assertEqual(banks[0], self.acc_b, "the chosen order is kept")
        text = self._html(file.invoice_id)
        self.assertIn("10035 01110 40008467011-58", text)
        self.assertIn("AFRILAND FIRST BANK", text)

    def test_11_no_configured_banks_falls_back_to_the_first_two(self):
        self.env.company.clearance_invoice_bank_ids = [(5, 0, 0)]
        file = self._billed_file()
        self.assertEqual(len(file.invoice_id._clearance_invoice_banks()), 2)

    # --- it must survive an invoice that is not a clearance one --------
    def test_12_an_ordinary_invoice_still_renders(self):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.client.id,
            'journal_id': self.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': "Consultancy", 'quantity': 1, 'price_unit': 50000,
                'account_id': self.income.id})]})
        text = self._html(invoice)
        self.assertIn("TOTAL TTC", text)
        self.assertNotIn("NBRE TC", text,
                         "no clearance file means no cargo box")
        self.assertNotIn("RESTE", text,
                         "and no advances to deduct")

    def test_13_only_a_clearance_invoice_swaps_odoos_report(self):
        file = self._billed_file()
        self.assertEqual(
            file.invoice_id._get_name_invoice_report(),
            'elite_clearance.report_clearance_invoice_document')
        ordinary = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.client.id,
            'journal_id': self.sale_journal.id})
        self.assertEqual(ordinary._get_name_invoice_report(),
                         'account.report_invoice_document',
                         "ordinary invoicing keeps Odoo's own document")

    def test_14_preview_opens_the_clearance_report(self):
        file = self._billed_file()
        action = file.action_preview_invoice()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_name'],
                         'elite_clearance.report_clearance_invoice')

    def test_15_previewing_an_unbilled_file_says_so(self):
        from odoo.exceptions import UserError
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4', 'partner_id': self.client.id,
            'service_type_id': self.service.id})
        with self.assertRaises(UserError):
            file.action_preview_invoice()
