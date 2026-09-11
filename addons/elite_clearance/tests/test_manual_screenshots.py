"""Pictures of the real application, for the user manual.

The owner cannot be asked to screenshot forty screens by hand, and a
manual drawn from memory is a manual that lies the first time a label
changes. CI already drives a real Chrome through this module, so the
same browser takes the pictures: every screen is the application as it
actually renders.

The database is branded and populated first - ELIMELEC SARL, a
plausible file, disbursements standing at each stage of their
workflow - because a manual illustrated with "YourCompany" and empty
lists teaches nobody anything. Every client, supplier and staff name
below is INVENTED: the manual circulates, and a real customer's
details do not belong in a document that circulates (owner,
11/09/2026).

Opt-in, because it is slow: set CLEARANCE_MANUAL_SHOTS. CI sets it on
the test job and the images come back under screenshots/ in the
browser-install artifact.

Every shot is attempted even when an earlier one fails, and the test
reports all the failures together at the end: one run should tell us
about every broken selector, not just the first.
"""

import contextlib
import os
import pathlib
import time

import odoo.tools
from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser, get_db_name

SHOOT = os.environ.get('CLEARANCE_MANUAL_SHOTS')

DEBOURS = [
    ("Retrait tardif", 23850),
    ("RTC Acconage & relevage", 1467524),
    ("Surestaries", 3094977),
    ("Transport Dry MSC", 220640),
]


@tagged('post_install', '-at_install')
class TestManualScreenshots(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not SHOOT:
            return
        env = cls.env
        company = env.company

        # --- the company the manual is written for -------------------
        company.write({
            'name': "ELIMELEC SARL",
            'street': "2eme Niveau Immeuble la Rose, Akwa",
            'city': "Douala", 'zip': "BP 5077",
            'phone': "(+237) 233 43 21 09",
            'email': "contact@elimelec-cm.example",
            'vat': "M051612521065D",
            'company_registry': "RC/DLA/2018/B/2056",
        })
        env.ref('base.user_admin').write({
            'name': "A. MBARGA", 'password': 'admin'})

        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        # The chart brings its own currency and the manual would then
        # quote dollars at a Douala clearing agent. The change has to
        # happen before anything is posted.
        francs = env.ref('base.XAF')
        francs.active = True
        company.currency_id = francs
        Account = env['account.account']

        def account(code, name, kind, reconcile=False):
            return Account.create({'code': code, 'name': name,
                                   'account_type': kind,
                                   'reconcile': reconcile})

        cls.engaged = account('M4716', "Debours engages", 'asset_current', True)
        cls.advances = account('M42110', "Personnel debours avances",
                               'asset_current', True)
        cls.income = account('M7062', "Honoraires de transit", 'income')
        cls.under = account('M6582', "Ajustement debours (charge)", 'expense')
        cls.over = account('M7582', "Ajustement debours (produit)", 'income')
        cls.sale_journal = env['account.journal'].create({
            'name': "Factures clients", 'type': 'sale', 'code': 'MSAL'})
        cls.cash = env['account.journal'].create({
            'name': "Caisse", 'type': 'cash', 'code': 'MCSH'})
        cls.vat = env['account.tax'].create({
            'name': "TVA 19,25%", 'amount': 19.25,
            'amount_type': 'percent', 'type_tax_use': 'sale'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_advance_account_id': cls.advances.id,
            'clearance_fee_account_id': cls.income.id,
            'clearance_commission_account_id': cls.income.id,
            'clearance_service_fee_account_id': cls.income.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_service_tax_ids': [(6, 0, cls.vat.ids)],
        })

        # --- an invented client, supplier and declarant --------------
        cls.client = env['res.partner'].create({
            'name': "SONICAM", 'is_company': True,
            'clearance_invoice_name':
                "SOCIETE NOUVELLE DES IMPORTS DU CAMEROUN",
            'street': "BP 4477 DOUALA - ZONE INDUSTRIELLE BASSA",
            'phone': "(+237) 691 000 111",
            'email': "imports@sonicam.example",
            'vat': "M071300046804A",
            'company_registry': "RC/DLA/2014/B/0771"})
        cls.vendor = env['res.partner'].create({
            'name': "Douala International Terminal",
            'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].search([], limit=1)
        cls.service = env['logistics.service.type'].search(
            [('code', '=', 'IM')], limit=1)
        cls.port = env['logistics.port'].search([], limit=1)
        cls.employee = env['hr.employee'].create({'name': "J. ETOUNDI"})

        def new_file(ref):
            return env['logistics.file'].create({
                'user_id': env.ref('base.user_admin').id,
                'partner_id': cls.client.id,
                'service_type_id': cls.service.id,
                'customs_regime': 'im4',
                'bl_awb_ref': ref,
                'client_reference': "CDE-2026-0413",
                'supplier_name': "SHANDONG CHUNLONG IMP & EXP",
                'customs_declaration_ref': "2026IM0540",
                'goods_description': "CARREAUX CERAMIQUE",
                'cargo_value': 41250000.0,
                'port_id': cls.port.id,
                'employee_id': cls.employee.id,
                'container_count': 2, 'container_type': "40",
                'package_count': 860, 'weight_kg': 14367.0})

        def receive_documents(file, leave_one_outstanding=False):
            """Tick the checklist the way the office does. Work cannot
            start while a mandatory document is missing - that gate is
            the point of chapter 4, so the picture shows a real
            checklist rather than a bypassed one."""
            lines = file.document_ids
            if leave_one_outstanding:
                lines = lines[1:]
            lines.write({'received': True,
                         'date_received': fields.Datetime.now()})

        def disbursement(file, description, amount):
            return env['logistics.expense'].create({
                'file_id': file.id, 'category_id': cls.category.id,
                'description': description, 'amount': amount,
                'vendor_id': cls.vendor.id})

        def settle(expense):
            expense.action_submit()
            expense.action_approve()
            expense.write({'payment_mode': 'cash',
                           'journal_id': cls.cash.id})
            expense.action_submit_settlement()
            expense.action_approve_settlement()
            expense.action_settle()

        # a file being worked, with disbursements standing at each stage
        cls.file_work = new_file("MSCU7741203")
        receive_documents(cls.file_work)
        cls.file_work.action_start_work()
        keyed = [disbursement(cls.file_work, d, a) for d, a in DEBOURS]
        cls.exp_submitted = keyed[1]
        cls.exp_submitted.action_submit()
        cls.exp_approved = keyed[2]
        cls.exp_approved.action_submit()
        cls.exp_approved.action_approve()

        # a file ready to bill
        cls.file_bill = new_file("MEDUW8830155")
        receive_documents(cls.file_bill)
        cls.file_bill.action_start_work()
        for description, amount in DEBOURS:
            settle(disbursement(cls.file_bill, description, amount))
        cls.file_bill.customs_fee_amount = 256974
        cls.file_bill.action_close_operations()

        # and one already billed, for the invoice chapter
        cls.file_done = new_file("CMAU4410987")
        receive_documents(cls.file_done)
        cls.file_done.action_start_work()
        settle(disbursement(cls.file_done, "RTC Acconage & relevage", 1467524))
        cls.file_done.customs_fee_amount = 256974
        cls.file_done.action_close_operations()
        env['logistics.billing.wizard'].with_context(
            active_id=cls.file_done.id).create({}).action_create_invoice()
        cls.invoice = cls.file_done.invoice_id
        cls.invoice.invoice_date = fields.Date.context_today(cls.invoice)

    # ------------------------------------------------------------------
    def _evaluate(self, browser, expression):
        """Run an expression in the page and return its value.

        _websocket_request already unwraps the envelope, so the payload
        is {'result': {'type': ..., 'value': ...}} - one level, not two.
        Reading it one key too deep returned None for everything, which
        looked exactly like "the element is not there" (11/09/2026).
        """
        answer = browser._websocket_request('Runtime.evaluate', params={
            'expression': expression, 'awaitPromise': False})
        return (answer or {}).get('result', {}).get('value')

    def _click(self, browser, selector):
        outcome = self._evaluate(browser, """
            (() => {
                const el = document.querySelector(%r);
                if (!el) { return "missing"; }
                el.click();
                return "clicked";
            })()
        """ % selector)
        if outcome != "clicked":
            raise AssertionError("nothing matched %s. Present: %s"
                                 % (selector, self._inventory(browser)))
        time.sleep(1.6)          # let Owl render what the click opened

    def _scroll_to(self, browser, selector):
        found = self._evaluate(browser, """
            (() => {
                const el = document.querySelector(%r);
                if (!el) { return "missing"; }
                el.scrollIntoView({block: "center"});
                return "scrolled";
            })()
        """ % selector)
        if found != "scrolled":
            raise AssertionError("nothing matched %s. Present: %s"
                                 % (selector, self._inventory(browser)))
        time.sleep(0.9)

    def _wait_for(self, browser, selector, timeout=25):
        """_wait_ready RETURNS on timeout rather than raising, so a
        missing element looks like a rendered page. Check it."""
        browser._wait_ready(
            "!!document.querySelector(%r)" % selector, timeout=timeout)
        if self._evaluate(browser, "!!document.querySelector(%r)" % selector):
            return
        raise AssertionError("%s never appeared. Present: %s"
                             % (selector, self._inventory(browser)))

    def _inventory(self, browser):
        """What the page actually offers, for when a selector misses."""
        return self._evaluate(browser, """
            (() => {
                const names = [...document.querySelectorAll("[name]")]
                    .map(e => e.tagName.toLowerCase() + "[" +
                              e.getAttribute("name") + "]");
                return [...new Set(names)].slice(0, 70).join(" ");
            })()
        """)

    # ------------------------------------------------------------------
    def test_01_the_screens_the_manual_shows(self):
        if not SHOOT:
            self.skipTest("set CLEARANCE_MANUAL_SHOTS to capture the manual")

        failures = []
        taken = []
        browser = ChromeBrowser(self, headless=True)
        with self.allow_requests(browser=browser), contextlib.ExitStack() as atexit:
            atexit.enter_context(browser.cleanup)
            self.authenticate('admin', 'admin', browser=browser)
            self.cr.flush()
            self.cr.clear()

            def shot(name, url, wait=".o_content", clicks=(), scroll=None):
                """One screen. A failure is recorded, never raised: one
                run should report every broken selector at once.

                save_test_file insists the prefix matches \\w*_ - a hyphen
                raises inside the screenshot's own callback, where nothing
                reports it.
                """
                try:
                    browser.navigate_to("%s%s" % (self.base_url(), url),
                                        wait_stop=True)
                    self._wait_for(browser, wait)
                    # wait for each thing just before touching it: a
                    # scroll target inside a dialog does not exist until
                    # the click that opens the dialog has happened
                    for selector in clicks:
                        self._wait_for(browser, selector, timeout=15)
                        self._click(browser, selector)
                    if scroll:
                        self._wait_for(browser, scroll, timeout=15)
                        self._scroll_to(browser, scroll)
                    time.sleep(1.0)
                    browser.take_screenshot(
                        "manual_%s_" % name).result(timeout=30)
                    taken.append(name)
                except Exception as error:                    # noqa: BLE001
                    failures.append("%s -> %s" % (name, error))

            def action(xmlid):
                return self.env.ref('elite_clearance.%s' % xmlid).id

            files = action('action_logistics_file')
            expenses = action('action_logistics_expense')
            form = "/odoo/action-%d/%%d" % files
            modal = ".modal .o_form_view"

            # 1-2  the application, and where the work waits
            shot("01_files", "/odoo/action-%d" % files)
            shot("02_my_tasks", "/odoo/action-%d"
                 % action('action_clearance_tasks'))

            # 3  opening a file
            shot("03_new_file", "/odoo/action-%d/new" % files,
                 wait=".o_form_view")
            shot("04_file_open", form % self.file_work.id, wait=".o_form_view")
            shot("05_cargo_routing", form % self.file_work.id,
                 wait=".o_form_view", scroll=".o_field_widget[name='not_containerised']")

            # 4  the document checklist
            shot("06_checklist", form % self.file_work.id, wait=".o_form_view",
                 scroll=".o_field_widget[name='document_ids']")

            # 5  recording a disbursement
            shot("07_expense_list", form % self.file_work.id,
                 wait=".o_form_view",
                 scroll=".o_field_widget[name='expense_ids']")
            shot("08_expense_dialog", form % self.file_work.id,
                 wait=".o_form_view",
                 clicks=[".o_field_widget[name='expense_ids'] "
                         ".o_field_x2many_list_row_add a"])

            # 6  approving it, and paying it
            shot("09_expense_submitted", "/odoo/action-%d/%d"
                 % (expenses, self.exp_submitted.id), wait=".o_form_view")
            shot("10_expense_settlement", "/odoo/action-%d/%d"
                 % (expenses, self.exp_approved.id), wait=".o_form_view")

            # 8  closing for operations
            shot("11_ops_close", form % self.file_bill.id, wait=".o_form_view")

            # 9  billing, and the split
            shot("12_billing_dialog", form % self.file_bill.id,
                 wait=".o_form_view",
                 clicks=["button[name='action_open_billing']"])
            shot("13_billing_totals", form % self.file_bill.id,
                 wait=".o_form_view",
                 clicks=["button[name='action_open_billing']"],
                 scroll="%s .oe_subtotal_footer" % modal)

            shot("18_billing_split", form % self.file_bill.id,
                 wait=".o_form_view",
                 clicks=["button[name='action_open_billing']",
                         "%s .o_field_widget[name='split_invoices'] input"
                         % modal],
                 scroll="%s .oe_subtotal_footer" % modal)

            # 10  the invoice, and the document the client receives
            shot("14_invoice_form", "/odoo/account.move/%d" % self.invoice.id,
                 wait=".o_form_view")
            shot("15_invoice_document",
                 "/report/html/elite_clearance.report_clearance_invoice/%d"
                 % self.invoice.id, wait=".o_clearance_invoice")

            # 11-12  reporting, and the settings behind it all
            shot("16_turnaround", "/odoo/action-%d"
                 % action('action_clearance_turnaround'))
            shot("17_settings", "/odoo/action-%d"
                 % action('action_clearance_config_settings'),
                 wait=".o_form_view")

            time.sleep(2.0)

        shots = pathlib.Path(odoo.tools.config['screenshots']) / get_db_name()
        written = sorted((shots / 'screenshots').glob('manual_*.png'))
        for image in written:
            self.assertGreater(image.stat().st_size, 4000, image.name)
        self.assertFalse(failures, "screens that did not capture:\n  - %s"
                         % "\n  - ".join(failures))
        self.assertEqual(len(written), len(taken))
