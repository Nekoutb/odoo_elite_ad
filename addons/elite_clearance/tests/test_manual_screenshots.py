"""Pictures of the real application, for the user manual and the UAT script.

The owner cannot be asked to screenshot fifty screens by hand, and a
manual drawn from memory is a manual that lies the first time a label
changes. CI already drives a real Chrome through this module, so the
same browser takes the pictures: every screen is the application as it
actually renders.

The database is branded and populated first - ELIMELEC SARL, plausible
files standing at every stage of their workflow, disbursements at each
step of theirs - because a manual illustrated with "YourCompany" and
empty lists teaches nobody anything. Every client, supplier and staff
name below is INVENTED: the manual circulates, and a real customer's
details do not belong in a document that circulates (owner,
11/09/2026).

Opt-in, because it is slow: set CLEARANCE_MANUAL_SHOTS. CI sets it on
the test job and the images come back under screenshots/ in the
browser-install artifact.

Every shot is attempted even when an earlier one fails, and the test
reports all the failures together at the end: one run should tell us
about every broken selector, not just the first. The records a screen
needs are built in the test itself, each group under its own
savepoint: a fixture that cannot be built costs its own pictures and
nothing else (08/10/2026).
"""

import base64
import contextlib
import logging
import os
import pathlib
import time

import odoo.tools
from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser, get_db_name

_logger = logging.getLogger(__name__)

SHOOT = os.environ.get('CLEARANCE_MANUAL_SHOTS')

DEBOURS = [
    ("Retrait tardif", 23850),
    ("RTC Acconage & relevage", 1467524),
    ("Surestaries", 3094977),
    ("Transport Dry MSC", 220640),
]

RECEIPT = base64.b64encode(b"%PDF-1.4 recu de caisse")


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
        # The manual must not quote dollars at a Douala clearing agent.
        # The company's CURRENCY cannot be swapped - account.company
        # refuses it once any journal item exists, and in a shared test
        # database they always do - so the currency it already has is
        # made to present as the franc: same symbol, same whole-franc
        # rounding as XAF. Cosmetic, and confined to the test database
        # that produces these pictures.
        # Only the symbol: the rounding cannot be reduced either once
        # entries exist, and the currency itself cannot be swapped.
        company.currency_id.write({'symbol': "FCFA", 'position': 'after'})
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
            'name': "Caisse principale", 'type': 'cash', 'code': 'MCSH'})
        cls.bank = env['account.journal'].create({
            'name': "AFRILAND FIRST BANK", 'type': 'bank', 'code': 'MAFB'})
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
            'is_company': True, 'supplier_rank': 1,
            'email': "facturation@dit-terminal.example"})
        cls.category = env['logistics.expense.category'].create({
            'name': "Frais portuaires", 'code': "M-PORT",
            'justification': 'justifiable'})
        cls.service = env['logistics.service.type'].search(
            [('code', '=', 'IM')], limit=1)
        cls.port = env['logistics.port'].search([], limit=1)
        cls.employee = env['hr.employee'].create({'name': "J. ETOUNDI"})
        # the person taking the pictures also holds a cash advance, so
        # My Tasks shows "Justify your cash advance" as the holder sees it
        cls.holder = env['hr.employee'].create({
            'name': "A. MBARGA", 'user_id': env.ref('base.user_admin').id})

        # a file being worked, with disbursements standing at each stage
        cls.file_work = cls._new_file("MSCU7741203")
        cls._receive(cls.file_work)
        cls._open(cls.file_work)
        keyed = [cls._disbursement(cls.file_work, d, a) for d, a in DEBOURS]
        cls.exp_submitted = keyed[1]
        cls.exp_submitted.action_submit()
        cls.exp_approved = keyed[2]
        cls.exp_approved.action_submit()
        cls.exp_approved.action_approve()

        # a file ready to bill
        cls.file_bill = cls._ready_to_bill("MEDUW8830155")

        # and one already billed, for the invoice chapter
        cls.file_done = cls._ready_to_bill("CMAU4410987", DEBOURS[1:2])
        cls.invoice = cls._bill(cls.file_done)

    # ------------------------------------------------------------- fixtures
    @classmethod
    def _new_file(cls, ref):
        return cls.env['logistics.file'].create({
            'user_id': cls.env.ref('base.user_admin').id,
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

    @classmethod
    def _receive(cls, file, leave_one_outstanding=False):
        """Tick the checklist the way the office does. Work cannot
        start while a mandatory document is missing - that gate is
        the point of the waiver chapter, so the picture shows a real
        checklist rather than a bypassed one."""
        lines = file.document_ids
        if leave_one_outstanding:
            lines = lines[1:]
        lines.write({'received': True,
                     'date_received': fields.Datetime.now()})

    @classmethod
    def _open(cls, file):
        """The real path (owner, 02/10/2026): the agent asks, the Head
        of Customer Service signs, and the signature starts the work."""
        file.action_request_opening()
        file.action_approve_opening()

    @classmethod
    def _disbursement(cls, file, description, amount, **extra):
        vals = {'file_id': file.id, 'category_id': cls.category.id,
                'description': description, 'amount': amount,
                'journal_id': cls.cash.id}
        if 'employee_id' not in extra:
            vals['vendor_id'] = cls.vendor.id
        vals.update(extra)
        return cls.env['logistics.expense'].create(vals)

    @classmethod
    def _approve_settlement(cls, expense):
        expense.action_submit()
        expense.action_approve()
        expense.action_submit_settlement()
        expense.action_approve_settlement()

    @classmethod
    def _pay(cls, expense):
        """Disburse through the dialog, with the till receipt attached:
        nothing is paid out without evidence (owner, 01/10/2026)."""
        wizard = cls.env['logistics.expense.settle.wizard'].with_context(
            active_id=expense.id).create({})
        receipt = cls.env['ir.attachment'].create({
            'name': "recu_caisse.pdf", 'res_model': wizard._name,
            'res_id': wizard.id, 'datas': RECEIPT})
        wizard.write({'attachment_ids': [(4, receipt.id)]})
        wizard.action_pay()

    @classmethod
    def _settle(cls, expense):
        cls._approve_settlement(expense)
        cls._pay(expense)

    @classmethod
    def _ready_to_bill(cls, ref, debours=DEBOURS):
        file = cls._new_file(ref)
        cls._receive(file)
        cls._open(file)
        for description, amount in debours:
            cls._settle(cls._disbursement(file, description, amount))
        file.customs_fee_amount = 256974
        file.action_close_operations()
        return file

    @classmethod
    def _bill(cls, file, post=False):
        cls.env['logistics.billing.wizard'].with_context(
            active_id=file.id).create({}).action_create_invoice()
        invoice = file.invoice_id
        invoice.invoice_date = fields.Date.context_today(invoice)
        if post:
            invoice.action_post()
        return invoice

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
    def _build_scenes(self):
        """The records the newer chapters show, each group under its own
        savepoint so that one that cannot be built costs only its own
        pictures. Returns {name: record_or_None} and the list of groups
        that failed."""
        cls = type(self)
        scenes = {}
        skipped = []

        def scene(name, build):
            try:
                with self.env.cr.savepoint():
                    scenes.update(build())
            except Exception as error:                        # noqa: BLE001
                self.env.invalidate_all()
                skipped.append("%s -> %s" % (name, error))

        def opening():
            draft = cls._new_file("OOLU2209911")
            cls._receive(draft)
            requested = cls._new_file("HLCU4471002")
            cls._receive(requested)
            requested.action_request_opening()
            refused = cls._new_file("MRKU6630075")
            cls._receive(refused)
            refused.action_request_opening()
            refused.write({'opening_note': (
                "La valeur en douane ne correspond pas a la facture "
                "fournisseur : verifier avant ouverture.")})
            refused.action_refuse_opening()
            return {'file_draft': draft, 'file_requested': requested,
                    'file_refused': refused}

        def waiver():
            waiting = cls._new_file("TCLU7781230")
            cls._receive(waiting, leave_one_outstanding=True)
            asked = cls._new_file("TEMU4452109")
            cls._receive(asked, leave_one_outstanding=True)
            asked.write({'waiver_reason': (
                "Original du connaissement attendu par DHL le 12/10 ; "
                "le navire est a quai et les surestaries courent.")})
            asked.action_request_waiver()
            return {'file_waiver': waiting, 'file_waiver_req': asked}

        def payment():
            to_pay = cls._disbursement(
                cls.file_work, "Frais de manutention terminal", 184500)
            cls._approve_settlement(to_pay)
            paid = cls._disbursement(
                cls.file_work, "Scanner conteneur", 61000)
            cls._settle(paid)
            return {'exp_pay': to_pay, 'exp_paid': paid}

        def advance():
            file = cls._new_file("SEGU5518870")
            cls._receive(file)
            cls._open(file)

            def staff_advance(description, amount):
                exp = cls._disbursement(file, description, amount,
                                        employee_id=cls.holder.id)
                cls._settle(exp)
                return exp

            held = staff_advance("Frais de transit portuaire", 150000)
            submitted = staff_advance("Droits de timbre et photocopies", 42500)
            self.env['ir.attachment'].create({
                'name': "justificatifs.pdf",
                'res_model': 'logistics.expense', 'res_id': submitted.id,
                'datas': RECEIPT})
            submitted.action_submit_justification()
            signed = staff_advance("Transport des plis en douane", 25000)
            self.env['ir.attachment'].create({
                'name': "recus_taxi.pdf",
                'res_model': 'logistics.expense', 'res_id': signed.id,
                'datas': RECEIPT})
            signed.action_submit_justification()
            signed.action_justify()
            return {'file_adv': file, 'exp_adv': held,
                    'exp_just': submitted, 'exp_just_ops': signed}

        def recharge():
            file = cls._ready_to_bill("CMAU5520018")
            file.write({
                'recharge_amount': file.oop_total - 150000,
                'recharge_reason': (
                    "Geste commercial convenu avec le client : une partie "
                    "des surestaries reste a notre charge.")})
            return {'file_recharge': file}

        def posted():
            file = cls._ready_to_bill("OOLU1193340")
            return {'file_posted': file,
                    'invoice_posted': cls._bill(file, post=True)}

        def closed():
            file = cls._ready_to_bill("MSKU2240911", DEBOURS[:2])
            cls._bill(file, post=True)
            file.action_mark_complete()
            return {'file_closed': file}

        def partial():
            file = cls._ready_to_bill("TGHU6604472", DEBOURS[:2])
            cls._bill(file, post=True)
            self.env['logistics.file.reopen.wizard'].create({
                'file_id': file.id, 'target_state': 'in_progress',
                'reason': "Facture de surestaries recue apres facturation."
            }).action_reopen()
            cls._settle(cls._disbursement(file, *DEBOURS[2]))
            file.action_close_operations()
            return {'file_partial': file}

        def void():
            file = cls._ready_to_bill("MSKU8812001", DEBOURS[:1])
            invoice = cls._bill(file, post=True)
            self.env['logistics.invoice.cancel.wizard'].create({
                'invoice_id': invoice.id,
                'reason': "Facture emise au mauvais client ; a refaire.",
            }).action_cancel_invoice()
            return {'invoice_void': invoice}

        def credit():
            file = cls._ready_to_bill("HLXU3309876")
            invoice = cls._bill(file, post=True)
            wizard = self.env['logistics.invoice.credit.wizard'].with_context(
                active_id=invoice.id).create({
                    'reason': "Surestaries facturees deux fois : la ligne "
                              "est annulee."})
            wizard.line_ids[:1].write({'selected': True})
            wizard.action_create_credit_note()
            note = self.env['account.move'].search([
                ('logistics_file_id', '=', file.id),
                ('move_type', '=', 'out_refund')], limit=1)
            return {'credit_note': note}

        def receipt():
            payment = self.env['account.payment'].create({
                'payment_type': 'inbound', 'partner_type': 'customer',
                'partner_id': cls.client.id, 'amount': 1500000,
                'journal_id': cls.bank.id,
                'date': fields.Date.context_today(self.env.user)})
            payment.action_post()
            return {'payment': payment}

        for name, build in (("opening", opening), ("waiver", waiver),
                            ("payment", payment), ("advance", advance),
                            ("recharge", recharge), ("posted", posted),
                            ("closed", closed), ("partial", partial),
                            ("void", void), ("credit", credit),
                            ("receipt", receipt)):
            scene(name, build)
        return scenes, skipped

    # ------------------------------------------------------------------
    def test_01_the_screens_the_manual_shows(self):
        if not SHOOT:
            self.skipTest("set CLEARANCE_MANUAL_SHOTS to capture the manual")

        scenes, skipped = self._build_scenes()
        for line in skipped:
            _logger.info("manual screenshots: scene not built: %s", line)

        failures = []
        taken = []
        browser = ChromeBrowser(self, headless=True)
        with self.allow_requests(browser=browser), contextlib.ExitStack() as atexit:
            atexit.enter_context(browser.cleanup)
            self.authenticate('admin', 'admin', browser=browser)
            self.cr.flush()
            self.cr.clear()

            def shot(name, url, wait=".o_content", clicks=(), scroll=None,
                     then=None):
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
                    if then:
                        self._wait_for(browser, then, timeout=15)
                    if scroll:
                        self._wait_for(browser, scroll, timeout=15)
                        self._scroll_to(browser, scroll)
                    time.sleep(1.0)
                    browser.take_screenshot(
                        "manual_%s_" % name).result(timeout=30)
                    taken.append(name)
                except Exception as error:                    # noqa: BLE001
                    failures.append("%s -> %s" % (name, error))

            def action(xmlid, module='elite_clearance'):
                return self.env.ref('%s.%s' % (module, xmlid)).id

            def scene_shot(key, name, url_fmt, **kw):
                """A shot of a scene record, skipped when the scene could
                not be built (already reported above)."""
                record = scenes.get(key)
                if record:
                    shot(name, url_fmt % record.id, **kw)

            files = action('action_logistics_file')
            expenses = action('action_logistics_expense')
            form = "/odoo/action-%d/%%d" % files
            expense_form = "/odoo/action-%d/%%d" % expenses
            modal = ".modal .o_form_view"
            by_action = "button[name='%d']"

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
            scene_shot('file_draft', "19_opening_request", form,
                       wait=".o_form_view")
            scene_shot('file_requested', "20_opening_approve", form,
                       wait=".o_form_view")
            scene_shot('file_refused', "21_opening_refused", form,
                       wait=".o_form_view")

            # 4  the document checklist, and the waiver
            shot("06_checklist", form % self.file_work.id, wait=".o_form_view",
                 scroll=".o_field_widget[name='document_ids']")
            scene_shot('file_waiver', "22_waiver_request", form,
                       wait=".o_form_view",
                       scroll=".o_field_widget[name='waiver_reason']")
            scene_shot('file_waiver_req', "23_waiver_approve", form,
                       wait=".o_form_view")

            # 5  recording a disbursement
            shot("07_expense_list", form % self.file_work.id,
                 wait=".o_form_view",
                 scroll=".o_field_widget[name='expense_ids']")
            shot("08_expense_dialog", form % self.file_work.id,
                 wait=".o_form_view",
                 clicks=["button[name='action_add_expense']"])

            # 6  approving it, keying the payment, paying it
            shot("09_expense_submitted", expense_form % self.exp_submitted.id,
                 wait=".o_form_view")
            shot("10_expense_settlement", expense_form % self.exp_approved.id,
                 wait=".o_form_view")
            scene_shot('exp_pay', "24_expense_pay", expense_form,
                       wait=".o_form_view")
            scene_shot('exp_pay', "25_settle_dialog", expense_form,
                       wait=".o_form_view",
                       clicks=["button[name='action_open_settle_wizard']"],
                       then=modal)
            scene_shot('exp_paid', "26_expense_paid", expense_form,
                       wait=".o_form_view",
                       scroll=".o_field_widget[name='payment_evidence_ids']")
            scene_shot('exp_paid', "27_send_evidence", expense_form,
                       wait=".o_form_view",
                       clicks=["button[name='action_send_payment_evidence']"],
                       then=modal)

            # 7  a cash advance, and its justification
            scene_shot('exp_adv', "28_advance_justify", expense_form,
                       wait=".o_form_view")
            scene_shot('exp_just', "29_justification_ops", expense_form,
                       wait=".o_form_view")
            scene_shot('exp_just_ops', "30_justification_finance",
                       expense_form, wait=".o_form_view")
            scene_shot('file_adv', "31_advance_gate", form,
                       wait=".o_form_view")

            # 8  closing for operations
            shot("32_ops_close_refused", form % self.file_work.id,
                 wait=".o_form_view",
                 clicks=["button[name='action_close_operations']"],
                 then=".modal")
            shot("11_ops_close", form % self.file_bill.id, wait=".o_form_view")

            # 9  billing, the recharge review and the split
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
            scene_shot('file_recharge', "33_recharge_approve", form,
                       wait=".o_form_view")

            # 10  the invoice, and the document the client receives
            shot("14_invoice_form", "/odoo/account.move/%d" % self.invoice.id,
                 wait=".o_form_view")
            shot("15_invoice_document",
                 "/report/html/elite_clearance.report_clearance_invoice/%d"
                 % self.invoice.id, wait=".o_clearance_invoice")
            scene_shot('file_posted', "34_file_close", form,
                       wait=".o_form_view")

            # 11  withdrawing a bill
            scene_shot('invoice_posted', "35_credit_wizard",
                       "/odoo/account.move/%d", wait=".o_form_view",
                       clicks=[by_action % action('action_invoice_credit_wizard')],
                       then=modal)
            scene_shot('invoice_posted', "36_cancel_wizard",
                       "/odoo/account.move/%d", wait=".o_form_view",
                       clicks=[by_action % action('action_invoice_cancel_wizard')],
                       then=modal)
            scene_shot('invoice_void', "37_invoice_cancelled",
                       "/odoo/account.move/%d", wait=".o_form_view")
            scene_shot('credit_note', "38_credit_note",
                       "/odoo/account.move/%d", wait=".o_form_view")

            # 12  closing, reopening, billing what arrived late
            scene_shot('file_closed', "39_file_closed", form,
                       wait=".o_form_view")
            scene_shot('file_closed', "40_reopen_wizard", form,
                       wait=".o_form_view",
                       clicks=[by_action % action('action_logistics_reopen_wizard')],
                       then=modal)
            scene_shot('file_partial', "41_billing_partial", form,
                       wait=".o_form_view",
                       clicks=["button[name='action_open_billing']"],
                       scroll="%s .o_field_widget[name='billed_line_ids']" % modal)

            # 13  a client's advance, received in Accounting
            scene_shot('payment', "42_payment_receipt",
                       "/odoo/account.payment/%d", wait=".o_form_view")
            scene_shot('payment', "43_payment_attribution",
                       "/odoo/account.payment/%d", wait=".o_form_view",
                       clicks=["button[name='action_clearance_attribute']"],
                       then=modal)

            # 14  reporting, settings and roles
            shot("16_turnaround", "/odoo/action-%d"
                 % action('action_clearance_turnaround'))
            shot("17_settings", "/odoo/action-%d"
                 % action('action_clearance_config_settings'),
                 wait=".o_form_view")
            shot("44_gm_settings", "/odoo/action-%d"
                 % action('action_clearance_settings_wizard'),
                 wait=".o_form_view")
            shot("45_user_roles", "/odoo/action-%d/%d"
                 % (action('action_res_users', 'base'),
                    self.env.ref('base.user_admin').id),
                 wait=".o_form_view")
            shot("46_invoices", "/odoo/action-%d"
                 % action('action_clearance_invoices'))

            time.sleep(2.0)

        shots = pathlib.Path(odoo.tools.config['screenshots']) / get_db_name()
        written = sorted((shots / 'screenshots').glob('manual_*.png'))
        for image in written:
            self.assertGreater(image.stat().st_size, 4000, image.name)
        self.assertFalse(failures, "screens that did not capture:\n  - %s"
                         % "\n  - ".join(failures))
        self.assertEqual(len(written), len(taken))
        _logger.info("manual screenshots: %d screens, %d scenes skipped",
                     len(taken), len(skipped))
