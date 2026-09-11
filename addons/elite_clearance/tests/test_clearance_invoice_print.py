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
            'company_registry': "RC/LBE/2013/B/0560",
            # Teese carried the handle; the bill carries the legal name
            'clearance_invoice_name': "CAPITAL TRADING PRIVATE LIMITED"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal P", 'is_company': True, 'street': "BP 1234 Douala", 'email': "client@test.cm", 'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001", 'clearance_invoice_name': "Full Legal Name SARL", 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port", 'code': "P-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Print test", 'code': "P-PRN", 'commission_rate': 2.0})
        cls.usd = env.ref('base.USD')
        cls.usd.active = True

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

    def _billed_file(self, amount=566899, quantity=None, split=False):
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4',
            'partner_id': self.client.id,
            'service_type_id': self.service.id,
            'bl_awb_ref': "MEDUWA265794",
            'client_reference': "LAMINATE BLEACH-063",
            'supplier_name': "SHANDONG GHUNLONG",
            'goods_description': "LAMINATE,BOTTLE CAP,",
            'container_count': 1, 'container_type': "40",
            'package_count': 865, 'weight_kg': 14367,
            # a declared value in a FOREIGN currency: this is the
            # expression that took the report down, and leaving it unset
            # is why the suite stayed green while printing failed
            'cargo_value': 284517.68,
            'cargo_value_currency_id': self.usd.id})
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
        wizard.split_invoices = split
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
        invoice = file.invoice_id
        words = invoice._clearance_amount_in_words(5797029)
        # Odoo's own amount_to_text would give English and append the
        # currency's UNIT LABEL ("Units"); the document does neither.
        self.assertTrue(words.endswith(invoice.currency_id.name), words)
        self.assertIn("MILLIONS", words, words)
        self.assertEqual(words, words.upper(), "the document shouts it")
        self.assertIn("QUATRE-VINGT", words, "French, not English")
        self.assertNotIn("THOUSAND", words, "French, not English")

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
        self.assertIn("Max period for complaints", text)
        self.assertIn(">30<", text, "the configured window is printed")
        self.assertIn("30 jours fin de mois", text)

    def test_07_amounts_are_space_grouped_to_the_currency_precision(self):
        """Space separators, and the CURRENCY decides the decimals.

        The old template hardcoded zero decimal places. XAF has none, so
        it looked right - but the precision is the currency's to decide,
        and this asserts that rather than a hardcoded shape.
        """
        nbsp = chr(160)
        invoice = self._billed_file().invoice_id
        text = invoice._clearance_money(6049966)
        self.assertTrue(text.startswith("6" + nbsp + "049" + nbsp + "966"),
                        repr(text))
        self.assertNotIn(",", text.split(",")[0],
                         "grouped with spaces, never commas")
        if invoice.currency_id.decimal_places:
            self.assertIn(",", text, repr(text))
        else:
            self.assertEqual(text, "6" + nbsp + "049" + nbsp + "966")

    def test_07b_a_zero_decimal_currency_prints_whole_units(self):
        """XAF has no minor unit and the invoice must not invent one."""
        nbsp = chr(160)
        invoice = self._billed_file().invoice_id
        xaf = self.env.ref('base.XAF')
        xaf.active = True
        invoice.currency_id = xaf
        self.assertEqual(invoice._clearance_money(6049966),
                         "6" + nbsp + "049" + nbsp + "966")
        self.assertEqual(invoice._clearance_money(53504),
                         "53" + nbsp + "504")

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
            'bl_awb_ref': "MEDUW000001",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'service_type_id': self.service.id})
        with self.assertRaises(UserError):
            file.action_preview_invoice()

    # --- Send & Print goes through Odoo's own report, not ours ---------
    def test_16_odoos_invoice_report_renders_our_document(self):
        """The one that was broken.

        Odoo 19 does not dispatch on _get_name_invoice_report(); it GUARDS
        on it, rendering account.report_invoice_document only when the name
        matches. Overriding the name without adding a branch made Send &
        Print produce a blank page. This proves the branch fires.
        """
        file = self._billed_file()
        rendered = self.env['ir.actions.report']._render_qweb_html(
            'account.report_invoice', file.invoice_id.ids)[0]
        text = rendered.decode() if isinstance(rendered, bytes) else rendered
        for label in ("Facture doit", "N° BL/N° LTA", "NBRE TC",
                      "Catégorie", "Sous total", "RESTE",
                      "MEDUWA265794"):
            self.assertIn(label, text, label)

    def test_17_an_ordinary_invoice_keeps_odoos_own_document(self):
        """Nothing outside clearance may change shape."""
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.client.id,
            'journal_id': self.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': "Consulting", 'quantity': 1, 'price_unit': 1000,
                'account_id': self.income.id})],
        })
        self.assertFalse(invoice.logistics_file_id)
        self.assertEqual(invoice._get_name_invoice_report(),
                         'account.report_invoice_document')
        rendered = self.env['ir.actions.report']._render_qweb_html(
            'account.report_invoice', invoice.ids)[0]
        text = rendered.decode() if isinstance(rendered, bytes) else rendered
        self.assertNotIn("N° BL/N° LTA", text,
                         "an ordinary invoice carries no shipment box")
        self.assertIn("Consulting", text, "and still prints its own lines")

    def test_18_a_clearance_invoice_asks_for_our_document(self):
        file = self._billed_file()
        self.assertEqual(
            file.invoice_id._get_name_invoice_report(),
            'elite_clearance.report_clearance_invoice_document')

    # --- the language must exist before the report asks for it ---------
    def test_19_the_report_never_asks_for_an_uninstalled_language(self):
        """"Invalid language code: fr_FR" took the whole invoice down.

        res.lang holds only INSTALLED languages. Forcing fr_FR made every
        t-field that formats a value raise, and the page never rendered.
        """
        installed = self.env['res.lang'].sudo().search([]).mapped('code')
        chosen = self._billed_file().invoice_id._clearance_report_lang()
        self.assertIn(chosen, installed,
                      "the report may only ask for a language that exists")

    def test_20_it_prints_with_no_french_installed(self):
        """The document's wording is hardcoded French either way."""
        french = self.env['res.lang'].sudo().search(
            [('code', '=like', 'fr%')])
        self.assertFalse(french, "this database has no French; that is the case")
        file = self._billed_file()
        text = self._html(file.invoice_id)          # must not raise
        self.assertIn("Facture doit", text)
        self.assertIn("Désignation", text)
        self.assertIn("284", text, "the foreign cargo value still prints")

    def test_21_it_prints_when_french_is_installed(self):
        lang = self.env['res.lang'].sudo().search(
            [('code', '=', 'fr_FR')], limit=1)
        if not lang:
            self.env['res.lang']._activate_lang('fr_FR')
            lang = self.env['res.lang'].sudo().search(
                [('code', '=', 'fr_FR')], limit=1)
        if not lang:
            self.skipTest("fr_FR is not available in this build")
        file = self._billed_file()
        self.assertEqual(
            file.invoice_id._clearance_report_lang(), 'fr_FR')
        self.assertIn("Facture doit", self._html(file.invoice_id))

    # --- the client's details are billing's business -------------------
    def test_22_billing_refuses_a_client_the_invoice_cannot_print(self):
        """Moved here from file creation, owner 06/09/2026."""
        from odoo.exceptions import UserError
        bare = self.env['res.partner'].create({
            'name': "Bare Client P", 'is_company': True})
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4', 'partner_id': bare.id,
            'service_type_id': self.service.id,
            'bl_awb_ref': "MEDUW000009",
            'goods_description': "Marchandises",
            'cargo_value': 500000.0})
        self.assertTrue(file.name, "opening the file is not blocked")
        file.state = 'in_progress'
        file.action_close_operations()
        with self.assertRaises(UserError) as caught:
            file.action_create_invoice()
        for expected in ("postal address", "e-mail", "Tax ID", "Company ID"):
            self.assertIn(expected, str(caught.exception), expected)

    def test_23_the_billing_screen_writes_back_to_the_customer(self):
        """The agent fixes the customer record, not just this invoice."""
        bare = self.env['res.partner'].create({
            'name': "Bare Client Q", 'is_company': True})
        file = self.env['logistics.file'].create({
            'customs_regime': 'im4', 'partner_id': bare.id,
            'service_type_id': self.service.id,
            'bl_awb_ref': "MEDUW000010",
            'goods_description': "Marchandises",
            'cargo_value': 500000.0})
        file.state = 'in_progress'
        file.action_close_operations()
        wizard = self.env['logistics.billing.wizard'].with_context(
            active_id=file.id).create({})
        self.assertTrue(wizard.client_details_missing)
        wizard.client_name = "BARE CLIENT TRADING LTD"
        wizard.client_street = "BP 999 Douala"
        wizard.client_email = "q@test.cm"
        wizard.client_vat = "M000000000777A"
        wizard.client_registry = "RC/DLA/2026/B/0777"
        wizard.customs_fee_amount = 100000        # something to bill
        self.assertFalse(wizard.client_details_missing)
        # written to the CUSTOMER, not held on the wizard
        self.assertEqual(bare.street, "BP 999 Douala")
        self.assertEqual(bare.vat, "M000000000777A")
        self.assertEqual(bare.company_registry, "RC/DLA/2026/B/0777")
        self.assertEqual(bare.clearance_invoice_name,
                         "BARE CLIENT TRADING LTD")
        self.assertEqual(bare.name, "Bare Client Q",
                         "the short handle everyone searches by is untouched")
        wizard.action_create_invoice()
        self.assertTrue(file.invoice_id)

    # --- a split bill: two documents, each the usual one ---------------
    def test_30_a_split_bill_prints_as_two_documents(self):
        """Owner 07/09/2026: the disbursements alone on one invoice - no
        VAT, so no VAT row - and the commission and fees on another, with
        the VAT row. Each deducts its own side's advances."""
        file = self._billed_file(split=True)
        file.write({'advance_had_amount': 256974,
                    'advance_had_vat_amount': 49467,
                    'advance_other_amount': 12345})
        self.assertTrue(file.debours_invoice_id)
        debours = self._html(file.debours_invoice_id)
        services = self._html(file.invoice_id)
        # the disbursements document
        self.assertIn("Retrait tardif", debours)
        self.assertIn("<td>Debours</td>", debours)
        self.assertNotIn("<td>Prestations</td>", debours)
        self.assertNotIn("Honoraires", debours)
        self.assertNotIn("TVA SUR PRESTATIONS", debours,
                         "no VAT on disbursements, so no VAT row")
        self.assertNotIn("AVANCE HAD/DAU", debours)
        self.assertIn("AUTRES AVANCES", debours)
        self.assertIn(file.debours_invoice_id._clearance_money(12345), debours)
        # the services document
        self.assertIn("Honoraires", services)
        self.assertNotIn("Retrait tardif", services)
        self.assertNotIn("<td>Debours</td>", services)
        self.assertIn("<td>Prestations</td>", services)
        self.assertIn("TVA SUR PRESTATIONS", services)
        self.assertIn("AVANCE HAD/DAU", services)
        self.assertIn("AVANCE TVA/HAD DAU", services)
        self.assertNotIn("AUTRES AVANCES", services)
        self.assertIn(file.invoice_id._clearance_money(49467), services)
        # and both are still the document, top to bottom
        for html in (debours, services):
            for label in ("Facture doit", "N° BL", "Produits", "TOTAL HT",
                          "TOTAL TTC", "RESTE",
                          "Arrêté la présente facture"):
                self.assertIn(label, html, label)

    def test_32_a_split_bill_previews_as_two_documents(self):
        """Preview renders the pair in one go, and the second document
        starts on its own page.

        Asserted on the HTML, deliberately: rendering a PDF inside a
        TransactionCase runs wkhtmltopdf against the live server while
        this transaction still holds its locks, and CI hung for an hour
        on exactly that (07/09/2026). The page break is a CSS rule, so
        the HTML is where it can honestly be checked.
        """
        file = self._billed_file(split=True)
        pair = file.debours_invoice_id | file.invoice_id
        html = self._html(pair)
        self.assertEqual(html.count('class="page o_clearance_invoice"'), 2,
                         "both documents in one print")
        self.assertIn(
            ".o_clearance_invoice + .o_clearance_invoice { page-break-before: always; }",
            html, "the second document must start on its own page")
        # each document is the right half
        first, second = html.split('class="page o_clearance_invoice"')[1:3]
        self.assertIn("Retrait tardif", first)
        self.assertNotIn("TVA SUR PRESTATIONS", first)
        self.assertIn("TVA SUR PRESTATIONS", second)

    def test_33_the_client_block_prints_the_full_legal_name(self):
        """Teese gave all 190 customers a short handle ("CTC"); the
        invoice must read the legal name instead (owner, 11/09/2026)."""
        file = self._billed_file()
        # the customer as Teese left it: a short handle, and the legal
        # name recorded separately
        self.client.name = "CTC"
        html = self._html(file.invoice_id)
        self.assertIn("CAPITAL TRADING PRIVATE LIMITED", html)
        self.assertNotIn(">CTC<", html,
                         "the handle is not what a client reads on a bill")
        # and with no legal name on record, an invoice raised before
        # today still prints exactly as it printed then
        self.client.clearance_invoice_name = False
        self.assertIn(">CTC<", self._html(file.invoice_id))

    def test_31_an_unsplit_bill_still_prints_every_row(self):
        """The model document shows all three advance rows, at zero if
        need be, and the VAT row - a plain bill keeps that."""
        file = self._billed_file()
        html = self._html(file.invoice_id)
        self.assertEqual(file.invoice_id.clearance_invoice_kind, 'full')
        for label in ("TVA SUR PRESTATIONS", "AVANCE HAD/DAU",
                      "AVANCE TVA/HAD DAU", "AUTRES AVANCES"):
            self.assertIn(label, html, label)
