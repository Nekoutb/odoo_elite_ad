"""The UAT script, run by the roles themselves (owner, 12/10/2026).

Thirteen logins, one per role of the script UAT-CL-01, each case of the
script executed as the role the script names, through the same access
rules, approval gates and wizards a person goes through. Every case runs
under its own savepoint: a failure is recorded with its message and the
next case still runs, so one run reports the whole script.

The report is written to <screenshots dir>/uat_report.md (the CI
artifact keeps it) and logged in full. The test fails at the end if any
case failed - a UAT failure is a defect.

What a browser alone can prove (drag-and-drop, the bell's sound and
toast, the look of a screen) is marked N/A here; the camera test and the
tours cover those.
"""

import base64
import contextlib
import json
import logging
import pathlib
import re

import odoo.tools
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged

from .holding import give_holding_account

_logger = logging.getLogger(__name__)

RECEIPT = base64.b64encode(b"%PDF-1.4 recu de caisse")
REFUSED = (UserError, ValidationError, AccessError)


@tagged('post_install', '-at_install', 'uat')
class TestUatRoles(TransactionCase):

    # ================================================================ setup
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']

        def account(code, name, kind, reconcile=False):
            return Account.create({'code': code, 'name': name,
                                   'account_type': kind, 'reconcile': reconcile})

        cls.engaged = account('U4716', "Debours engages", 'asset_current', True)
        cls.pending = account('U4711', "Debours a engager", 'liability_current', True)
        cls.advances = account('U42110', "Personnel debours avances", 'asset_current', True)
        cls.income = account('U7062', "Honoraires de transit", 'income')
        cls.commission = account('U7063', "Commissions sur debours", 'income')
        cls.service_fee = account('U7064', "Honoraires agrees en douane", 'income')
        cls.file_fee = account('U7065', "Frais de dossier", 'income')
        cls.under = account('U6582', "Ajustement debours (charge)", 'expense')
        cls.over = account('U7582', "Ajustement debours (produit)", 'income')
        Journal = env['account.journal']
        cls.sale_journal = Journal.create({'name': "Factures clients UAT", 'type': 'sale', 'code': 'USAL'})
        cls.misc_journal = Journal.create({'name': "Operations diverses UAT", 'type': 'general', 'code': 'UOD'})
        cls.cash = Journal.create({'name': "Caisse principale UAT", 'type': 'cash', 'code': 'UCSH'})
        cls.bank = Journal.create({'name': "Banque UAT", 'type': 'bank', 'code': 'UBNK'})
        give_holding_account(cls.bank)
        cls.vat = env['account.tax'].create({
            'name': "TVA 19,25% UAT", 'amount': 19.25,
            'amount_type': 'percent', 'type_tax_use': 'sale'})
        cls.default_tax = env['account.tax'].create({
            'name': "TVA defaut UAT", 'amount': 19.25,
            'amount_type': 'percent', 'type_tax_use': 'sale'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_oop_payable_account_id': cls.pending.id,
            'clearance_advance_account_id': cls.advances.id,
            'clearance_fee_account_id': cls.income.id,
            'clearance_commission_account_id': cls.commission.id,
            'clearance_service_fee_account_id': cls.service_fee.id,
            'clearance_file_fee_account_id': cls.file_fee.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_misc_journal_id': cls.misc_journal.id,
            'clearance_service_tax_ids': [(6, 0, cls.vat.ids)],
            'clearance_letterhead_tagline': "Commissionnaire en Douane Agree",
            'clearance_cash_voucher_title': "AVANCE FRAIS",
        })

        # --- the people: one login per role of the script ---------------
        G = 'elite_clearance.group_clearance_'

        def user(name, *groups):
            return env['res.users'].create({
                'name': name,
                'login': re.sub(r'[^a-z]+', '.', name.lower()).strip('.') + "@uat.test",
                'group_ids': [(6, 0, [env.ref(g).id for g in groups])]})

        cls.cs = user("UAT Customer Service Agent", G + 'customer_service')
        cls.csm = user("UAT Head of Customer Service", G + 'customer_service_manager')
        cls.ops = user("UAT Operations Agent", G + 'operations')
        cls.opsm = user("UAT Head of Service Operations", G + 'ops_manager')
        cls.tr = user("UAT Transit Agent", G + 'transit')
        cls.trm = user("UAT Head of Service Transit", G + 'transit_manager')
        cls.fin = user("UAT Finance Agent", G + 'finance')
        cls.finm = user("UAT Head of Service Finance", G + 'finance_manager')
        cls.cash_user = user("UAT Cashier", G + 'cashier')
        cls.tres = user("UAT Treasury", G + 'treasury')
        cls.bill = user("UAT Billing Agent", G + 'billing')
        cls.gm = user("UAT General Manager", G + 'manager')
        cls.adm = user("UAT Clearance Administrator", G + 'admin')
        cls.roles = {
            'CS': cls.cs, 'CSM': cls.csm, 'OPS': cls.ops, 'OPSM': cls.opsm,
            'TR': cls.tr, 'TRM': cls.trm, 'FIN': cls.fin, 'FINM': cls.finm,
            'CASH': cls.cash_user, 'TRES': cls.tres, 'BILL': cls.bill,
            'GM': cls.gm, 'ADM': cls.adm}

        # --- master data, invented ----------------------------------------
        cls.client = env['res.partner'].create({
            'name': "SONICAM UAT", 'is_company': True,
            'clearance_invoice_name': "SOCIETE NOUVELLE DES IMPORTS DU CAMEROUN",
            'street': "BP 4477 DOUALA", 'email': "imports@sonicam.example",
            'vat': "M071300046804A", 'company_registry': "RC/DLA/2014/B/0771"})
        cls.exempt_client = env['res.partner'].create({
            'name': "ONG EXONEREE UAT", 'is_company': True,
            'clearance_invoice_name': "ONG EXONEREE", 'street': "BP 1 DOUALA",
            'email': "ong@exempt.example", 'vat': "M000000000099X",
            'company_registry': "RC/DLA/2020/B/0099", 'clearance_vat_exempt': True})
        cls.vendor = env['res.partner'].create({
            'name': "Douala International Terminal UAT", 'is_company': True,
            'supplier_rank': 1, 'email': "facturation@dit-terminal.example"})
        cls.vendor_no_mail = env['res.partner'].create({
            'name': "Transporteur sans e-mail UAT", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Frais portuaires UAT", 'code': "U-PORT", 'justification': 'justifiable'})
        cls.category_nj = env['logistics.expense.category'].create({
            'name': "Pourboires UAT", 'code': "U-TIP", 'justification': 'non_justifiable'})
        cls.service = env['logistics.service.type'].search([('code', '=', 'IM')], limit=1)
        if not cls.service:
            cls.service = env['logistics.service.type'].create({
                'name': "Import Maritime", 'code': "IM", 'commission_rate': 2.0})
        if not cls.service.commission_rate:
            cls.service.commission_rate = 2.0
        cls.port = env['logistics.port'].search([], limit=1) or env['logistics.port'].create(
            {'name': "Douala UAT", 'code': "UDLA"})
        cls.incoterm = (env['account.incoterms'].search([('code', '=', 'CIF')], limit=1)
                        or env['account.incoterms'].create(
                            {'name': "Cost, Insurance and Freight", 'code': 'CIF'}))
        # the advance holder is the Operations Agent's own employee record
        cls.holder = env['hr.employee'].create({
            'name': "UAT Operations Agent", 'user_id': cls.ops.id})
        cls.results = []
        cls.seq = 0

    # ============================================================ helpers
    def _ref(self):
        type(self).seq += 1
        return "UATU%07d" % self.seq

    def _file(self, user=None, partner=None, **extra):
        vals = {
            'partner_id': (partner or self.client).id,
            'service_type_id': self.service.id,
            'customs_regime': 'im4', 'bl_awb_ref': self._ref(),
            'client_reference': "CDE-UAT", 'supplier_name': "SHANDONG UAT",
            'customs_declaration_ref': "2026IM0540",
            'goods_description': "CARREAUX CERAMIQUE", 'cargo_value': 41250000.0,
            'cargo_value_currency_id': self.env.company.currency_id.id,
            'shipment_type': 'container', 'importer_name': "SONICAM",
            'incoterm_id': self.incoterm.id, 'port_id': self.port.id, 'container_count': 2, 'container_type': "40",
            'package_count': 860, 'weight_kg': 14367.0}
        vals.update(extra)
        return self.env['logistics.file'].with_user(user or self.cs).create(vals)

    def _receive(self, file, leave_one=False):
        lines = file.document_ids.sudo()
        if leave_one:
            lines = lines - lines.filtered('is_mandatory')[:1]
        lines.write({'received': True, 'date_received': fields.Datetime.now()})

    def _open(self, file):
        file.with_user(self.cs).action_request_opening()
        file.with_user(self.csm).action_approve_opening()
        return file

    def _working(self):
        file = self._file()
        self._receive(file)
        return self._open(file)

    def _cost(self, file, description="Manutention", amount=100000, user=None,
              journal=None, vendor=True, employee=None, category=None, quote=True):
        vals = {'file_id': file.id, 'category_id': (category or self.category).id,
                'description': description, 'amount': amount,
                'journal_id': (journal or self.cash).id}
        if employee:
            vals['employee_id'] = employee.id
        elif vendor:
            vals['vendor_id'] = (vendor if vendor is not True else self.vendor).id
        exp = self.env['logistics.expense'].with_user(user or self.ops).create(vals)
        if quote:
            self._attach(exp, "devis.pdf", exp.create_uid)
        return exp

    def _attach(self, record, name, user, **extra):
        vals = {'name': name, 'res_model': record._name, 'res_id': record.id,
                'datas': RECEIPT}
        vals.update(extra)
        return self.env['ir.attachment'].with_user(user).create(vals)

    def _head_of(self, exp):
        return {'operations': self.opsm, 'customer_service': self.csm,
                'transit': self.trm}.get(exp.originating_team, self.opsm)

    def _approved(self, exp):
        exp.with_user(exp.create_uid).action_submit()
        exp.with_user(self._head_of(exp)).action_approve()
        return exp

    def _signed(self, exp):
        self._approved(exp)
        exp.with_user(self.fin).action_submit_settlement()
        exp.with_user(self.finm).action_approve_settlement()
        return exp

    def _pay(self, exp, with_receipt=None):
        """Through the dialog, as the Cashier (till) or Treasury (bank)."""
        user = self.cash_user if exp.journal_id.type == 'cash' else self.tres
        if with_receipt is None:
            with_receipt = exp.journal_id.type != 'cash'
        wizard = self.env['logistics.expense.settle.wizard'].with_user(
            user).with_context(active_id=exp.id).create({})
        if with_receipt:
            receipt = self._attach(wizard, "recu.pdf", user)
            wizard.write({'attachment_ids': [(4, receipt.id)]})
        wizard.action_pay()
        return exp

    def _paid(self, file, description="Manutention", amount=100000, **kw):
        return self._pay(self._signed(self._cost(file, description, amount, **kw)))

    def _sign_voucher(self, exp):
        signed = self.env['ir.attachment'].with_user(self.cash_user).create({
            'name': "avance_frais_signee.pdf", 'res_model': exp._name, 'res_id': 0,
            'datas': RECEIPT})
        exp.with_user(self.cash_user).write({'signed_voucher_ids': [(4, signed.id)]})
        return signed

    def _ready(self, file=None, costs=((("Manutention", 100000), ("Surestaries", 250000)))):
        file = file or self._working()
        for description, amount in costs:
            self._sign_voucher(self._paid(file, description, amount))
        file.sudo().customs_fee_amount = 256974
        file.with_user(self.opsm).action_close_operations()
        return file

    def _wizard(self, file, user=None, review=False, **vals):
        ctx = {'active_id': file.id}
        if review:
            ctx['clearance_billing_review'] = True
        return self.env['logistics.billing.wizard'].with_user(
            user or self.bill).with_context(**ctx).create(vals)

    def _bill(self, file, post=True, **vals):
        """Bill through the screen; returns the document(s) THIS billing
        issued (two for a split bill), posted unless asked otherwise."""
        before = file.sudo()._client_invoices()
        self._wizard(file, **vals).action_create_invoice()
        invoices = file.sudo()._client_invoices() - before
        if post:
            for inv in invoices:
                inv.with_user(self.bill).action_post()
        return invoices

    def _queue(self, user, kind):
        return self.env['clearance.task'].with_user(user).search([('kind', '=', kind)])

    def _queued(self, user, kind, record):
        return any(t.res_model == record._name and t.res_id == record.id
                   for t in self._queue(user, kind))

    def _refuse(self, user, record, method, reason):
        return self.env['clearance.rejection.wizard'].with_user(user).create({
            'res_model': record._name, 'res_ids': str(record.id),
            'method': method, 'reason': reason}).action_confirm()

    def _bus(self):
        queued = self.env.cr.precommit.data.get("bus.bus.values", [])
        return [json.loads(row["message"]) for row in queued
                if json.loads(row["message"])["type"] == 'elite_clearance.task']

    def _arch(self, user, xmlid='elite_clearance.logistics_file_view_form'):
        view = self.env.ref(xmlid)
        return self.env[view.model].with_user(user).get_view(view.id)['arch']

    def _html(self, report, records):
        return self.env['ir.actions.report']._render_qweb_html(
            report, records.ids)[0].decode()

    # --------------------------------------------------------- recording
    @contextlib.contextmanager
    def case(self, cid, title, roles):
        try:
            with self.env.cr.savepoint():
                yield
        except Exception as error:                            # noqa: BLE001
            self.env.invalidate_all()
            text = " ".join(str(error).split())[:240]
            self.results.append((cid, title, roles, 'FAIL',
                                 "%s: %s" % (type(error).__name__, text)))
            _logger.warning("UAT %s FAIL - %s: %s", cid, type(error).__name__, text, exc_info=True)
        else:
            self.results.append((cid, title, roles, 'PASS', ""))

    def na(self, cid, title, roles, why):
        self.results.append((cid, title, roles, 'N/A', why))

    def check(self, condition, message):
        if not condition:
            raise AssertionError(message)

    def refused(self, callable_, message):
        try:
            callable_()
        except REFUSED:
            return
        raise AssertionError(message)

    # ================================================================ run
    def test_01_the_script_run_by_the_roles(self):
        self.d_configuration()
        self.e_opening()
        self.f_disbursements()
        self.g_closing()
        self.h_advances()
        self.i_billing()
        self.j_withdrawing()
        self.k_partial_and_closure()
        self.l_monitoring()
        self._report()

    # ---------------------------------------------------------------- D
    def d_configuration(self):
        company = self.env.company
        with self.case('UAT-01', "Every setting the application needs is filled in", 'GM'):
            before = company.clearance_invoice_complaint_days
            self.env['clearance.settings.wizard'].with_user(self.gm).create(
                {'clearance_invoice_complaint_days': before + 1})
            self.check(company.clearance_invoice_complaint_days == before + 1,
                       "the General Manager's page saves without administrator rights")
            self.env['clearance.settings.wizard'].with_user(self.gm).create(
                {'clearance_invoice_complaint_days': before})
            for field in ('clearance_oop_account_id', 'clearance_oop_payable_account_id',
                          'clearance_advance_account_id', 'clearance_fee_account_id',
                          'clearance_commission_account_id', 'clearance_service_fee_account_id',
                          'clearance_file_fee_account_id', 'clearance_oop_undercharge_account_id',
                          'clearance_oop_overcharge_account_id', 'clearance_misc_journal_id',
                          'clearance_sale_journal_id'):
                self.check(company[field], "%s is set" % field)
            tax = company.clearance_service_tax_ids
            self.check(tax and tax.type_tax_use == 'sale' and abs(tax.amount - 19.25) < 0.01,
                       "VAT on Service Fees is a 19.25% sale tax")
            self.check(company.clearance_oop_account_id != company.clearance_oop_payable_account_id,
                       "the two 471 accounts differ")

        with self.case('UAT-01b', "Numbering continues from the old system", 'GM'):
            service = self.service.with_user(self.gm)
            service.write({'legacy_last_file_ref': "2026IM0900"})
            file = self._file()
            self.check(file.name == "2026IM0901", "next number is 2026IM0901, got %s" % file.name)
            self.refused(lambda: service.write({'legacy_last_file_ref': "IM-2026-99"}),
                         "a malformed reference is refused")
            self.refused(lambda: service.write({'legacy_last_file_ref': "2026IM0001"}),
                         "a reference behind a file opened here is refused")

        with self.case('UAT-02', "Each role sees only what it may act on", 'all'):
            File = self.env['logistics.file']
            File.with_user(self.cs).check_access('create')
            self.refused(lambda: File.with_user(self.ops).check_access('create'),
                         "only Customer Service opens a file")
            self.refused(lambda: self.env['account.move'].with_user(self.opsm).check_access('read'),
                         "a Head of Service Operations does not see Invoices")
            self.env['account.move'].with_user(self.bill).check_access('read')
            self.check('action_open_billing' in self._arch(self.bill), "Billing sees the Billing button")
            self.check('action_open_billing' not in self._arch(self.ops), "Operations does not")
            self.check('action_approve_opening' in self._arch(self.csm), "the CS head sees Approve Opening")
            self.check('action_approve_opening' not in self._arch(self.opsm), "the Ops head does not")
            self.check('action_mark_complete' in self._arch(self.csm), "the CS head sees Close the File")
            self.check('action_mark_complete' not in self._arch(self.bill), "Billing does not")
            for user in self.roles.values():
                self.env['clearance.task'].with_user(user).search([], limit=1)

        with self.case('UAT-02b', "The Clearance Administrator passes every gate", 'ADM'):
            adm = self.adm
            file = self._file(user=adm)
            self._receive(file)
            file.with_user(adm).action_request_opening()
            file.with_user(adm).action_approve_opening()
            exp = self._cost(file, user=adm)
            exp = exp.with_user(adm)
            exp.action_submit()
            exp.action_approve()
            exp.action_submit_settlement()
            exp.action_approve_settlement()
            self.env['logistics.expense.settle.wizard'].with_user(adm).with_context(
                active_id=exp.id).create({}).action_pay()
            self.check(exp.state == 'settled', "paid by the one login")
            self.refused(lambda: self.env['res.users'].with_user(adm).check_access('write'),
                         "Settings → Users is not theirs")
            company.clearance_expense_approver_ids = [(6, 0, self.opsm.ids)]
            try:
                other = self._cost(file, "Scanner", 20000, user=adm)
                other.with_user(adm).action_submit()
                other.with_user(adm).action_approve()
            finally:
                company.clearance_expense_approver_ids = [(5, 0, 0)]

    # ---------------------------------------------------------------- E
    def e_opening(self):
        with self.case('UAT-03', "Open a clearance file", 'CS'):
            file = self._file()
            self.check(re.match(r'2026IM\d{4}$', file.name), "reference shape, got %s" % file.name)
            self.check(file.analytic_account_id.name == "%s - %s" % (file.name, self.client.clearance_slug),
                       "analytic account named after the file and the slug")
            self.check(file.state == 'draft' and file.opening_state == 'none', "draft, opening not requested")
            from lxml import etree
            tree = etree.fromstring(self._arch(self.cs))
            self.check(not tree.xpath("//field[@name='employee_id'][not(ancestor::field)]"),
                       "no Follow-up Employee on the form")
            self.uat03 = file

        with self.case('UAT-03b', "Cargo and routing are mandatory", 'CS'):
            file = self._file()
            with self.assertRaises(AssertionError):
                with Form(file.with_user(self.cs)) as form:
                    form.port_id = self.env['logistics.port']
            file.invalidate_recordset()
            with Form(file.with_user(self.cs)) as form:
                form.not_containerised = True
            self.check(file.not_containerised and not file.container_count,
                       "Not Containerised clears the container figures")

        with self.case('UAT-04', "Every team sees every file, draft included", 'CS, OPS, TR'):
            file = self._file()
            for user in (self.ops, self.tr):
                self.check(self.env['logistics.file'].with_user(user).search([('id', '=', file.id)]),
                           "%s sees the draft" % user.name)
                with Form(file.with_user(user)):
                    pass

        with self.case('UAT-04b', "The Head of Customer Service approves the opening", 'CS, CSM'):
            file = self._file()
            self._receive(file)
            file.with_user(self.cs).action_request_opening()
            self.check('Head of Customer Service' in (file.stage_owner or ''), "the banner names the CS head")
            self.check(not self._queue(self.opsm, 'file_open'), "the Ops head has no such row")
            self.check(file in self._queue(self.csm, 'file_open').mapped('file_id'), "the CS head has it")
            self.refused(lambda: file.with_user(self.opsm).action_approve_opening(), "the Ops head may not approve")
            file.with_user(self.csm).action_approve_opening()
            self.check(file.state == 'in_progress', "approval starts the work")
            second = self._file()
            self._receive(second)
            second.with_user(self.cs).action_request_opening()
            self.refused(lambda: self._refuse(self.csm, second, 'action_refuse_opening', ""),
                         "a refusal without a reason is refused")
            self._refuse(self.csm, second, 'action_refuse_opening', "Valeur en douane a verifier.")
            self.check(second.opening_state == 'refused' and "verifier" in (second.opening_note or ''),
                       "the reason is on the file")
            self.check(any("verifier" in (m.body or '') and self.cs.partner_id in m.partner_ids
                           for m in second.message_ids), "the author is notified with the reason")
            second.with_user(self.cs).action_request_opening()

        with self.case('UAT-05', "Receive the documents", 'OPS'):
            file = self._file()
            lines = file.document_ids.with_user(self.ops)
            self.check(lines, "a checklist was generated from the service type")
            lines[:2].write({'received': True})
            self.check(all(lines[:2].mapped('date_received')), "Received On stamps itself")
            self._attach(file, "connaissement.pdf", self.ops)
            self.check(file.attachment_ids, "the dropped file is listed")
        self.na('UAT-05', "Drag-and-drop anywhere on the checklist area", 'OPS',
                "browser only - covered by the expense dialog tour")

        with self.case('UAT-06', "A missing document goes through a waiver", 'CS, CSM'):
            file = self._file()
            self._receive(file, leave_one=True)
            self.refused(lambda: file.with_user(self.cs).action_request_opening(),
                         "no opening request with a mandatory document missing")
            file.with_user(self.cs).write({'waiver_reason': "Original du BL attendu le 12/10."})
            file.with_user(self.cs).action_request_waiver()
            for user in (self.opsm, self.gm):
                self.refused(lambda u=user: file.with_user(u).action_approve_waiver(),
                             "%s may not approve the waiver" % user.name)
            self.check(file in self._queue(self.csm, 'doc_waiver').mapped('file_id'), "the CS head's queue")
            file.with_user(self.csm).action_approve_waiver()
            self.check(file.state == 'in_progress', "the waiver starts the work")
            self.check(self.env['logistics.file'].with_user(self.tr).search([('id', '=', file.id)]),
                       "visible to everyone")

    # ---------------------------------------------------------------- F
    def f_disbursements(self):
        with self.case('UAT-07', "Key a disbursement and submit it in one press", 'OPS'):
            file = self._working()
            Wizard = self.env['logistics.expense.capture.wizard'].with_user(self.ops)
            Wizard.with_context(active_id=file.id).create({
                'category_id': self.category.id, 'description': "Manutention terminal",
                'amount': 150000, 'journal_id': self.cash.id,
                'vendor_id': self.vendor.id}).action_submit_close()
            Wizard.with_context(active_id=file.id).create({
                'category_id': self.category.id, 'description': "Frais de transit",
                'amount': 50000, 'journal_id': self.cash.id,
                # the dialog no longer names a holder: the advance stands
                # against the requester (owner 13/10/2026)
                'is_advance': True}).action_submit_close()
            rows = file.expense_ids.sorted('id')
            self.check(len(rows) == 2 and set(rows.mapped('state')) == {'submitted'}, "both rows submitted")
            self.check(rows[0].payment_mode == 'cash' and rows[1].payment_mode == 'advance',
                       "the mode followed what was keyed: %s" % rows.mapped('payment_mode'))
            self.check(self.env['logistics.expense']._fields['description'].string == "Additional Comments",
                       "the free text reads Additional Comments")
            domain = str(self.env['logistics.expense']._fields['journal_id'].domain)
            self.check('cash' in domain and 'bank' in domain, "the channel list is tills and banks: %s" % domain)

        with self.case('UAT-08', "The head of the service that keyed it approves it", 'CSM, OPSM'):
            file = self._working()
            exp = self._cost(file)
            exp.with_user(self.ops).action_submit()
            self.check(not self._queued(self.csm, 'expense_approve', exp),
                       "the CS head's queue does not list Operations' cost")
            self.refused(lambda: exp.with_user(self.csm).action_approve(), "the CS head may not approve it")
            self.check(self._queued(self.opsm, 'expense_approve', exp), "the Ops head's queue")
            exp.with_user(self.opsm).action_approve()
            self.check(exp.state == 'approved' and exp.approved_by_id == self.opsm, "approved, recorded against the head")
            self.check(not exp.accrual_move_id, "no journal entry yet")
            cs_cost = self._cost(file, "Photocopies", 5000, user=self.cs)
            cs_cost.with_user(self.cs).action_submit()
            self.check(self._queued(self.csm, 'expense_approve', cs_cost)
                       and not self._queued(self.opsm, 'expense_approve', cs_cost),
                       "the CS cost is in the CS head's queue only")
            other = self._cost(file, "Scanner", 20000)
            other.with_user(self.ops).action_submit()
            self._refuse(self.opsm, other, 'action_refuse', "Devis non conforme.")
            self.check(other.state != 'submitted', "refused")
            self.check(any("non conforme" in (m.body or '') and self.ops.partner_id in m.partner_ids
                           for m in other.message_ids), "the reason reaches the requester")

        with self.case('UAT-09', "Finance confirms or corrects the payment - and the debt is recognised", 'OPS, FIN'):
            file = self._working()
            exp = self._approved(self._cost(file))
            self.refused(lambda: exp.with_user(self.ops).write({'journal_id': self.bank.id}),
                         "the agent's payment fields are Finance's now")
            self.check(self._queued(self.fin, 'settlement_key', exp),
                       "Finance's queue has it without anybody sending it")
            exp.with_user(self.fin).write({'journal_id': self.bank.id})
            self.check(exp.payment_mode == 'electronic', "the mode follows the channel")
            exp.with_user(self.fin).action_submit_settlement()
            move = exp.accrual_move_id
            self.check(move and move.state == 'posted' and move.journal_id == self.misc_journal,
                       "an entry posted in the miscellaneous journal")
            debit = move.line_ids.filtered(lambda l: l.debit)
            credit = move.line_ids.filtered(lambda l: l.credit)
            self.check(debit.account_id == self.pending and credit.account_id == self.vendor.property_account_payable_id,
                       "Dr Debours a engager / Cr the vendor's payable")
            self.check(all(move.line_ids.mapped('analytic_distribution')), "every line carries the analytic")

        with self.case('UAT-10', "The Head of Service Finance signs the settlement", 'FINM'):
            file = self._working()
            exp = self._approved(self._cost(file))
            exp.with_user(self.fin).action_submit_settlement()
            self.check(self._queued(self.finm, 'settlement_approve', exp), "the FINM queue")
            moves = exp.accrual_move_id
            exp.with_user(self.finm).action_approve_settlement()
            self.check(exp.state == 'settlement_approved' and exp.accrual_move_id == moves, "signed, no new entry")
            back = self._approved(self._cost(file, "Plombage", 15000))
            back.with_user(self.fin).action_submit_settlement()
            self._refuse(self.finm, back, 'action_return_settlement', "Mauvais journal.")
            self.check(back.state == 'approved', "returned to Finance")

        with self.case('UAT-11', "The Cashier pays from the till - the voucher is printed", 'CASH'):
            file = self._working()
            exp = self._signed(self._cost(file))
            self.check(self._queued(self.cash_user, 'disburse_cash', exp), "Pay from cash")
            self._pay(exp, with_receipt=False)
            self.check(exp.state == 'settled' and exp.date_settled, "paid with nothing attached")
            self.check(exp.cash_voucher_ids, "the voucher was printed into its box")
            self.check(not exp.payment_evidence_ids and exp.request_document_ids, "request documents stay apart")
            move = exp.settlement_move_id
            self.check(move and len(move.line_ids) == 4, "four lines")
            label = "%s / %s" % (self.category.name, file.name)
            self.check(all(l.name == label for l in move.line_ids), "every line reads category / file: %s" % move.line_ids.mapped('name'))
            accounts = move.line_ids.mapped('account_id')
            self.check(self.engaged in accounts and self.pending in accounts
                       and self.cash.default_account_id in accounts, "the four accounts")
            html = self._html('elite_clearance.report_cash_voucher', exp)
            self.check("AVANCE FRAIS" in html and self.client.clearance_invoice_name in html
                       and "Commissionnaire" in html, "the voucher prints title, client and tagline")
            bank_exp = self._signed(self._cost(file, "Virement", 80000, journal=self.bank))
            self.refused(lambda: self._pay(bank_exp, with_receipt=False), "a bank payment still needs evidence")
            self._pay(bank_exp, with_receipt=True)
            self.check(bank_exp.state == 'settled' and bank_exp.payment_evidence_ids, "paid from the bank with evidence")

        with self.case('UAT-11c', "The signed voucher comes back, or the file does not close", 'CASH, OPSM'):
            file = self._working()
            exp = self._paid(file)
            file.sudo().customs_fee_amount = 100000
            self.refused(lambda: file.with_user(self.opsm).action_close_operations(),
                         "refused while the voucher is unsigned")
            signed = self._sign_voucher(exp)
            self.check(signed in exp.signed_voucher_ids and signed not in exp.request_document_ids
                       and signed.clearance_kind == 'signed', "the signed copy sits in its own box")
            file.with_user(self.opsm).action_close_operations()
            self.check(file.state == 'ops_closed', "closed once signed")

        with self.case('UAT-11b', "Customer Service sends the third party its proof of payment", 'CS'):
            file = self._working()
            exp = self._paid(file, journal=self.bank)
            self.refused(lambda: exp.with_user(self.ops).action_send_payment_evidence(), "Operations has no such button")
            no_mail = self._paid(file, "Transport", 30000, journal=self.bank, vendor=self.vendor_no_mail)
            self.refused(lambda: no_mail.with_user(self.cs).action_send_payment_evidence(), "a vendor without e-mail is refused")
            action = exp.with_user(self.cs).action_send_payment_evidence()
            ctx = action['context']
            composer = self.env['mail.compose.message'].with_user(self.cs).with_context(ctx).create(
                {'body': "<p>Ci-joint la preuve de paiement.</p>"})
            composer._action_send_mail()
            exp.invalidate_recordset()
            self.check(exp.payment_evidence_sent_date and exp.payment_evidence_sent_by_id == self.cs,
                       "the timeline reads Evidence Sent with the sender")
            self.check(any(self.vendor in m.partner_ids for m in exp.message_ids), "the vendor is the recipient")

        with self.case('UAT-12', "Segregation holds", 'OPS, FIN'):
            file = self._working()
            exp = self._approved(self._cost(file))
            self.refused(lambda: exp.with_user(self.ops).write({'vendor_id': self.vendor_no_mail.id}),
                         "the agent cannot change an approved cost's third party")
            self.refused(lambda: self._cost(file, user=self.fin), "Finance never keys")
            exp.with_user(self.fin).action_submit_settlement()
            self.refused(lambda: exp.with_user(self.opsm).action_approve_settlement(),
                         "the head who approved does not sign the settlement")

        with self.case('UAT-12b', "Every refusal says why", 'all'):
            file = self._file()
            self._receive(file, leave_one=True)
            file.with_user(self.cs).write({'waiver_reason': "BL en route."})
            file.with_user(self.cs).action_request_waiver()
            self.refused(lambda: self._refuse(self.csm, file, 'action_refuse_waiver', ""), "no empty reason")
            self._refuse(self.csm, file, 'action_refuse_waiver', "Attendre l'original.")
            self.check(file.waiver_state == 'refused', "waiver refused")
            working = self._working()
            adv = self._paid(working, "Timbres", 20000, employee=self.holder)
            self._attach(adv, "recus.pdf", self.ops)
            adv.with_user(self.ops).action_submit_justification()
            self._refuse(self.opsm, adv, 'action_refuse_justification', "Recus illisibles.")
            self.check(adv.state == 'settled', "justification refused, back with the holder")
            self.check(any("illisibles" in (m.body or '') for m in adv.message_ids), "reason in the chatter")

        with self.case('UAT-13', "A cash advance to a member of staff", 'OPS, FIN, FINM, CASH, holder, OPSM, FINM'):
            file = self._working()
            adv = self._cost(file, "Transit portuaire", 150000, employee=self.holder, quote=False)
            self.check(adv.payment_mode == 'advance', "Via employee cash advance")
            self._pay(self._signed(adv), with_receipt=False)
            move = adv.settlement_move_id
            line = move.line_ids.filtered(lambda l: l.account_id == self.advances)
            self.check(line and line.debit == 150000 and line.partner_id == self.holder.work_contact_id,
                       "421101 debited against the holder")
            self.check(self.engaged not in move.line_ids.mapped('account_id'), "never 47xx yet")
            self.check(self._queued(self.ops, 'advance_justify', adv), "in the holder's own My Tasks")
            self.check(not self._queued(self.tr, 'advance_justify', adv), "and nobody else's")
            self.refused(lambda: adv.with_user(self.ops).action_submit_justification(),
                         "the voucher alone is not a justification")
            self._attach(adv, "recus.pdf", self.ops)
            adv.with_user(self.ops).action_submit_justification()
            self.refused(lambda: adv.with_user(self.finm).action_justify(), "the Ops head signs the documents first")
            adv.with_user(self.opsm).action_justify()
            self.check(not adv.justification_move_id, "nothing posts on the first signature")
            adv.with_user(self.finm).action_justify_finance()
            jm = adv.justification_move_id
            self.check(jm and jm.line_ids.filtered(lambda l: l.debit).account_id == self.engaged
                       and jm.line_ids.filtered(lambda l: l.credit).account_id == self.advances,
                       "the second signature posts 421101 -> 47xx")

        with self.case('UAT-14', "A cost that can never be justified", 'OPS, FIN, CASH'):
            file = self._working()
            exp = self._paid(file, "Pourboire", 5000, employee=self.holder, category=self.category_nj)
            self.check(not exp.justification_required, "not justifiable")
            debit = exp.settlement_move_id.line_ids.filtered(lambda l: l.debit)
            self.check(self.engaged in debit.mapped('account_id') and self.advances not in debit.mapped('account_id'),
                       "debits 47xx straight away")
            self.refused(lambda: exp.with_user(self.ops).action_submit_justification(), "no justification possible")
            self.check("action_submit_justification" in self._arch(self.ops, 'elite_clearance.logistics_expense_view_form')
                       and "justification_required" in self._arch(self.ops, 'elite_clearance.logistics_expense_view_form'),
                       "the button is hidden by justification_required")
            self.check(not file.unjustified_advance_total, "does not block the file")

    # ---------------------------------------------------------------- G
    def g_closing(self):
        with self.case('UAT-15', "Operations close is gated", 'OPSM'):
            file = self._working()
            unpaid = self._approved(self._cost(file))
            self.refused(lambda: file.with_user(self.opsm).action_close_operations(), "refused without the fee")
            file.sudo().customs_fee_amount = 256974
            self.refused(lambda: file.with_user(self.opsm).action_close_operations(), "refused while a cost is unpaid")
            unpaid.with_user(self.fin).action_submit_settlement()
            unpaid.with_user(self.finm).action_approve_settlement()
            self._pay(unpaid, with_receipt=False)
            self.refused(lambda: file.with_user(self.opsm).action_close_operations(), "refused while the voucher is unsigned")
            self._sign_voucher(unpaid)
            adv = self._paid(file, "Avance", 40000, employee=self.holder)
            self._sign_voucher(adv)
            self.check(file.unjustified_advance_total == 40000, "an unjustified advance")
            self.refused(lambda: file.with_user(self.opsm).action_close_operations(), "refused while the advance is unjustified")
            self.refused(lambda: file.with_user(self.opsm).action_request_advance_waiver(), "a waiver needs its explanation")
            file.with_user(self.opsm).write({'advance_waiver_reason': "Justificatifs attendus la semaine prochaine."})
            file.with_user(self.opsm).action_request_advance_waiver()
            file.with_user(self.opsm).action_approve_advance_waiver()
            file.with_user(self.opsm).action_close_operations()
            self.check(file.state == 'ops_closed' and file.unjustified_advance_total == 40000,
                       "the waiver releases the file, never the money")

        with self.case('UAT-16', "Close for operations", 'OPSM'):
            file = self._ready()
            self.check(file.state == 'ops_closed', "OK for Billing")
            self.check('Billing' in (file.stage_owner or ''), "sitting with Billing")
            self.check(file in self._queue(self.bill, 'billing').mapped('file_id'), "in Billing's My Tasks")

    # ---------------------------------------------------------------- H
    def h_advances(self):
        with self.case('UAT-17', "Record a client advance in Accounting and see it at billing", 'FIN, TRES, BILL'):
            file = self._ready()
            payment = self.env['account.payment'].create({
                'payment_type': 'inbound', 'partner_type': 'customer',
                'partner_id': self.client.id, 'amount': 1500000,
                'journal_id': self.bank.id, 'date': fields.Date.context_today(self.env.user)})
            payment.action_post()
            self.check(payment.clearance_needs_attribution, "the blue banner: no file yet")
            theirs = self._ready(self._working_for(self.exempt_client))
            wizard = self.env['logistics.payment.attribution.wizard'].with_user(self.tres).with_context(
                active_id=payment.id).create({})
            self.check(file in wizard.candidate_ids and theirs not in wizard.candidate_ids,
                       "this client's open files are offered, no other customer's")
            wizard.write({'file_id': file.id})
            wizard.action_attribute()
            self.check(payment.logistics_file_id == file, "attributed")
            analytic = str(file.analytic_account_id.id)
            self.check(all(analytic in (l.analytic_distribution or {}) for l in payment.move_id.line_ids),
                       "every line of the receipt carries the file's analytic")
            self.check(self._wizard(file).advance_other_amount == 1500000, "the billing screen shows it under Other advances")

    # ---------------------------------------------------------------- I
    def i_billing(self):
        with self.case('UAT-18', "The billing screen", 'BILL'):
            file = self._ready()
            w = self._wizard(file)
            self.check(w.client_name == self.client.clearance_invoice_name and w.client_vat == self.client.vat,
                       "the client block")
            self.check(w.shipment_bl_awb_ref == file.bl_awb_ref, "the shipment block")
            self.check(len(w.debours_line_ids) == 2 and 'comment' in w.debours_line_ids._fields, "disbursements with a Why column")
            w.write({'commission_rate': 2.0, 'customs_fee_amount': 256974, 'file_fee_amount': 25000})
            self.check(w.advance_had_amount == 256974 and w.advance_had_vat_amount > 0,
                       "the HAD figure replicated into the advance and its VAT")
            missing = self._ready(self._working())
            missing.partner_id.sudo().write({'email': False})
            w2 = self._wizard(missing)
            self.check(w2.client_details_missing, "missing client details are flagged")
            # the client block is read-only (owner 14/10/2026): Customer
            # Service completes the record, and the screen then reads it
            self.refused(lambda: w2.action_create_invoice(), "no invoice while the record is incomplete")
            missing.partner_id.with_user(self.cs).write({'email': "imports@sonicam.example"})
            w3 = self._wizard(missing)
            self.check(not w3.client_details_missing and w3.client_email == "imports@sonicam.example",
                       "completed by Customer Service, read by the screen")

        with self.case('UAT-19', "Recharging at other than cost needs approval", 'BILL, OPSM, GM'):
            file = self._ready()
            w = self._wizard(file)
            line = w.debours_line_ids[0]
            line.write({'amount_recharged': line.amount_engaged - 50000})
            self.check(w.needs_review, "any line off cost needs the review")
            self.refused(w.action_submit_for_review, "a variance with no Why is refused")
            line.write({'comment': "Geste commercial."})
            w.action_submit_for_review()
            self.check(file.recharge_state == 'requested', "sent for review")
            self.refused(lambda: self._bill(file), "no invoice while the review is pending")
            self.check(file in self._queue(self.opsm, 'recharge_ops').mapped('file_id'), "the Ops head's queue")
            review = self._wizard(file, user=self.opsm, review=True)
            self.check(review.review_mode and review.debours_line_ids[0].comment == "Geste commercial.",
                       "the review opens on the billing screen with the Why")
            review.action_approve_review()
            self.check(file.recharge_ops_approved_by_id == self.opsm, "Operations signed")
            self.refused(lambda: self._bill(file), "below cost also needs the General Manager")
            self._attach(file, "accord_client.pdf", self.bill)
            self._wizard(file, user=self.gm, review=True).action_approve_review()
            self.check(file.recharge_state == 'approved', "approved by both")
            invoices = self._bill(file)
            self.check(invoices and invoices.state == 'posted', "Resume Billing issues the invoice")
            adjust = invoices.invoice_line_ids.filtered(lambda l: l.clearance_category == 'adjustment')
            self.check(adjust and adjust.account_id == self.under, "the undercharge on its own P&L account")
            # offsetting lines still need the review; the refusal resets the figures
            second = self._ready()
            w = self._wizard(second)
            a, b = w.debours_line_ids[0], w.debours_line_ids[1]
            a.write({'amount_recharged': a.amount_engaged + 30000, 'comment': "Majoration."})
            b.write({'amount_recharged': b.amount_engaged - 30000, 'comment': "Geste."})
            self.check(w.needs_review, "the pair that cancels out still needs the review")
            w.action_submit_for_review()
            self.refused(lambda: self._refuse(self.opsm, second, 'action_refuse_recharge', ""), "no empty reason")
            self._refuse(self.opsm, second, 'action_refuse_recharge', "Pas d'accord.")
            self.check(second.recharge_state == 'refused' and not second.recharge_amount
                       and not any(second.expense_ids.mapped('recharge_amount')), "refusal resets every figure")
            self.check(not self._wizard(second).needs_review, "the screen proposes cost again")

        with self.case('UAT-20', "Raise the invoice", 'BILL'):
            file = self._ready()
            inv = self._bill(file, post=False)
            lines = inv.invoice_line_ids
            debours = lines.filtered(lambda l: l.clearance_category == 'debours')
            services = lines - debours
            self.check(debours and not debours.tax_ids, "disbursements carry no VAT")
            self.check(sum(debours.mapped('price_subtotal')) == 350000 and set(debours.mapped('account_id')) == {self.engaged},
                       "47xx credited in full")
            commission = services.filtered(lambda l: l.account_id == self.commission)
            self.check(commission and "Commission sur débours" in commission.name and "%" not in commission.name,
                       "commission line without percentage: %s" % commission.mapped('name'))
            self.check(services.filtered(lambda l: l.account_id == self.service_fee), "HAD on its own 706")
            self.check(all(services.mapped('tax_ids')), "services carry VAT")
            inv.with_user(self.bill).action_post()
            analytic = str(file.analytic_account_id.id)
            bare = inv.line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')
                                         and analytic not in (l.analytic_distribution or {}))
            self.check(not bare, "analytic on every line; missing on %s" % [
                (l.display_type, l.account_id.code, l.name) for l in bare])

        with self.case('UAT-20b', "VAT follows the settings and the customer", 'BILL, GM'):
            company = self.env.company
            first = self._bill(self._ready(), post=False)
            self.check(self.vat in first.invoice_line_ids.tax_ids, "VAT from the Clearance setting")
            company.clearance_service_tax_ids = [(5, 0, 0)]
            company.account_sale_tax_id = self.default_tax
            try:
                second = self._bill(self._ready(), post=False)
                self.check(self.default_tax in second.invoice_line_ids.tax_ids, "then Accounting's default tax")
                exempt = self._bill(self._ready(self._working_for(self.exempt_client)), post=False)
                self.check(not exempt.invoice_line_ids.tax_ids, "none for the exempt customer")
                company.account_sale_tax_id = False
                self.refused(lambda: self._bill(self._ready()), "nothing configured and not exempt: refused")
            finally:
                company.clearance_service_tax_ids = [(6, 0, self.vat.ids)]
                company.account_sale_tax_id = False

        with self.case('UAT-21', "The printed document", 'BILL'):
            file = self._ready()
            inv = self._bill(file)
            html = self._html('elite_clearance.report_clearance_invoice', inv)
            for word in ("TOTAL TTC", "RESTE", self.client.clearance_invoice_name, "bours", "Prestations"):
                self.check(word.lower() in html.lower(), "the document prints %s" % word)
            self.check(file.with_user(self.bill).action_preview_invoice(), "Preview Invoice opens for Billing")

        with self.case('UAT-22', "Split the bill", 'BILL'):
            file = self._ready()
            invoices = self._bill(file, split_invoices=True)
            self.check(len(invoices) == 2, "two invoices")
            deb = invoices.filtered(lambda i: i.clearance_invoice_kind == 'debours')
            srv = invoices.filtered(lambda i: i.clearance_invoice_kind == 'services')
            self.check(deb and srv and deb.name != srv.name, "two numbers, one per kind")
            self.check(not deb.invoice_line_ids.tax_ids and srv.invoice_line_ids.tax_ids, "VAT on services only")
            self.check(file.invoice_id == srv and file.debours_invoice_id == deb, "the file points at both")
            self.check(file.invoices_posted, "complete when both are posted")

        with self.case('UAT-23', "Post it", 'BILL'):
            file = self._ready()
            inv = self._bill(file, post=False)
            self.check(inv.state == 'draft' and inv.name in ('/', False) or inv.name.startswith('EL'), "draft first")
            inv.with_user(self.bill).action_post()
            self.check(re.match(r'EL\d\dIM\d{4}$', inv.name or ''), "final number EL26IM…, got %s" % inv.name)
            advances = file.advance_had_amount + file.advance_had_vat_amount + file.advance_other_amount
            self.check(abs(file.invoice_balance_due - (inv.amount_total - advances)) < 1,
                       "balance due %s = total %s less advances %s" % (file.invoice_balance_due, inv.amount_total, advances))

    # ---------------------------------------------------------------- J
    def j_withdrawing(self):
        with self.case('UAT-24', "Credit part of an invoice", 'BILL'):
            file = self._ready()
            inv = self._bill(file)
            Wizard = self.env['logistics.invoice.credit.wizard'].with_user(self.bill)
            self.refused(lambda: Wizard.with_context(active_id=inv.id).create({'reason': ""}).action_create_credit_note(),
                         "the reason is demanded first")
            w = Wizard.with_context(active_id=inv.id).create({'reason': "Surestaries facturees deux fois."})
            line = w.line_ids.filtered(lambda l: 'Surestaries' in (l.name or ''))[:1] or w.line_ids[:1]
            line.write({'selected': True})
            w.action_create_credit_note()
            note = self.env['account.move'].search([('logistics_file_id', '=', file.id), ('move_type', '=', 'out_refund')])
            self.check(note and note.state == 'posted' and note.name.startswith('AV26'), "a posted AV26… credit note: %s" % note.mapped('name'))
            self.check(inv.amount_residual < inv.amount_total, "set against the invoice")
            html = self._html('elite_clearance.report_clearance_invoice', note)
            self.check("Avoir" in html and inv.name in html, "prints as Avoir naming the invoice")

        with self.case('UAT-25', "What was credited can be billed again", 'BILL'):
            file = self._ready()
            inv = self._bill(file)
            w = self.env['logistics.invoice.credit.wizard'].with_user(self.bill).with_context(
                active_id=inv.id).create({'reason': "Ligne en trop."})
            w.line_ids[:1].write({'selected': True})
            w.action_create_credit_note()
            again = self._wizard(file)
            self.check(len(again.debours_line_ids) == 1 and len(again.billed_line_ids) == 1,
                       "the credited disbursement is back, the other greyed as Already billed")

        with self.case('UAT-26', "Cancel an invoice", 'BILL'):
            file = self._ready()
            inv = self._bill(file)
            Wizard = self.env['logistics.invoice.cancel.wizard'].with_user(self.bill)
            self.refused(lambda: Wizard.create({'invoice_id': inv.id, 'reason': ""}).action_cancel_invoice(), "a reason is required")
            Wizard.create({'invoice_id': inv.id, 'reason': "Mauvais client."}).action_cancel_invoice()
            self.check(inv.state == 'posted' and inv.clearance_voided, "stays posted, marked cancelled")
            self.check(abs(inv.amount_residual) < 1, "the mirror entry clears it")
            self.check(file.has_billable and not file.bill_stands, "the file is billable again")

    # ---------------------------------------------------------------- K
    def k_partial_and_closure(self):
        with self.case('UAT-27', "A cost that arrives late", 'OPSM, OPS, BILL'):
            file = self._ready()
            self._bill(file)
            self.env["logistics.file.reopen.wizard"].with_user(self.csm).create({
                'reason_id': self.env.ref('elite_clearance.reopen_reason_other').id, 'file_id': file.id, 'target_state': 'in_progress',
                'reason': "Facture de surestaries recue apres facturation."}).action_reopen()
            self.check(file.state == 'in_progress', "back to operations")
            late = self._paid(file, "Surestaries tardives", 90000)
            self._sign_voucher(late)
            file.with_user(self.opsm).action_close_operations()
            w = self._wizard(file)
            self.check(w.debours_line_ids.mapped('expense_id') == late, "only the new cost is listed")
            self.check(len(w.billed_line_ids) == 2, "the earlier ones greyed")
            self.check(not w.customs_fee_amount, "the customs fee already charged is not proposed again")
            second = self._bill(file)
            self.check(len(file.sudo()._client_invoices()) == 2 or len(file.invoice_ids) >= 2, "a second invoice for the late cost")
            self.check(sum(second.invoice_line_ids.filtered(lambda l: l.clearance_category == 'debours').mapped('price_subtotal')) == 90000,
                       "for the new cost alone")

        with self.case('UAT-28', "The Head of Customer Service closes the file", 'BILL, CSM'):
            file = self._ready()
            inv = self._bill(file, post=False)
            self.check(file not in self._queue(self.csm, 'file_close').mapped('file_id'), "not in the queue until posted")
            inv.with_user(self.bill).action_post()
            self.refused(lambda: file.with_user(self.bill).action_mark_complete(), "Billing has no Close the File")
            self.check(file in self._queue(self.csm, 'file_close').mapped('file_id'), "the CS head's queue")
            file.with_user(self.csm).action_mark_complete()
            self.check(file.state == 'done', "Closed")

        with self.case('UAT-29', "A closed file is closed", 'BILL, OPSM'):
            file = self._ready()
            inv = self._bill(file)
            file.with_user(self.csm).action_mark_complete()
            Credit = self.env['logistics.invoice.credit.wizard'].with_user(self.bill)
            self.refused(lambda: Credit.with_context(active_id=inv.id).create({'reason': "Erreur."}).action_create_credit_note(),
                         "no credit note on a closed file")
            Reopen = self.env['logistics.file.reopen.wizard']
            self.refused(lambda: Reopen.with_user(self.bill).create({
                'reason_id': self.env.ref('elite_clearance.reopen_reason_other').id, 'file_id': file.id, 'target_state': 'ops_closed', 'reason': "Avoir."}).action_reopen(),
                "Billing may not reopen")
            Reopen.with_user(self.csm).create({
                'reason_id': self.env.ref('elite_clearance.reopen_reason_other').id, 'file_id': file.id, 'target_state': 'ops_closed', 'reason': "Avoir a emettre."}).action_reopen()
            self.check(file.state == 'ops_closed', "back to billing")
            w = Credit.with_context(active_id=inv.id).create({'reason': "Ligne en trop."})
            w.line_ids[:1].write({'selected': True})
            w.action_create_credit_note()

    # ---------------------------------------------------------------- L
    def l_monitoring(self):
        with self.case('UAT-30', "My Tasks, and the bell", 'all'):
            kinds = {}
            for tag, user in self.roles.items():
                kinds[tag] = set(self.env['clearance.task'].with_user(user).search([]).mapped('kind'))
            self.check(kinds['OPSM'] != kinds['BILL'] != kinds['CSM'], "each role's list is different")
            before = len(self._bus())
            file = self._working()
            exp = self._cost(file)
            exp.with_user(self.ops).action_submit()
            rung = [m for m in self._bus()[before:] if m['payload']['kind'] == 'expense_approve']
            self.check(rung, "the head's bell rings on submit")
            rows = self.env['clearance.task'].with_user(self.opsm).search([], order='date_landed desc', limit=5)
            self.check(rows and rows[0].date_landed >= rows[-1].date_landed, "newest first")
        self.na('UAT-30', "The tone, the toast and the live count", 'all',
                "browser only - covered by the systray tour")

        with self.case('UAT-30b', "Ongoing files, and three queues that now ring", 'OPS, CSM, BILL'):
            file = self._working()
            self._cost(file)
            ongoing = self.env['clearance.task'].with_user(self.ops).search([('kind', '=', 'ongoing_file')])
            self.check(file in ongoing.mapped('file_id'), "Ongoing files lists it for the requester")
            self.check(not any(m['payload']['kind'] == 'ongoing_file' for m in self._bus()), "the bell does not count it")
            before = len(self._bus())
            ready = self._ready()
            inv = self._bill(ready, post=False)
            inv.with_user(self.bill).action_post()
            self.check(any(m['payload']['kind'] == 'file_close' for m in self._bus()[before:]), "the CS head rings when the last document posts")
            before = len(self._bus())
            self.env['logistics.invoice.cancel.wizard'].with_user(self.bill).create(
                {'invoice_id': inv.id, 'reason': "Retiree."}).action_cancel_invoice()
            self.check(any(m['payload']['kind'] == 'billing' for m in self._bus()[before:]), "Billing rings when a bill is withdrawn")
            before = len(self._bus())
            self.env['logistics.billing.service'].with_user(self.bill).create({'name': "Escorte UAT", 'default_amount': 25000})
            self.check(any(m['payload']['kind'] == 'billing_service' for m in self._bus()[before:]), "and when a service line is proposed")

        with self.case('UAT-31', "Turnaround", 'any'):
            Turnaround = self.env['clearance.turnaround']
            self.check(Turnaround._fields['target_hours'].type == 'float', "targets in hours, fractional")
            rows = Turnaround.with_user(self.ops).search([], limit=5)
            self.check(rows, "rows exist for the files worked")
            self.check('hours_taken' in rows._fields and 'is_late' in rows._fields, "hours taken against the target")

        with self.case('UAT-32', "Every document issued", 'BILL'):
            action = self.env.ref('elite_clearance.action_clearance_invoices')
            domain = odoo.tools.safe_eval.safe_eval(action.domain)
            docs = self.env['account.move'].with_user(self.bill).search(domain)
            self.check(set(docs.mapped('move_type')) >= {'out_invoice', 'out_refund'}, "invoices and credit notes together")
            self.check(docs.filtered('clearance_voided'), "the cancelled ones are there, under their flag")
            self.refused(lambda: self.env['account.move'].with_user(self.opsm).search(domain), "not for the Ops head")

    # ------------------------------------------------------------- report
    def _working_for(self, partner):
        file = self._file(partner=partner)
        self._receive(file)
        return self._open(file)

    def _report(self):
        lines = ["| Case | Title | Role(s) | Result | Note |", "|---|---|---|---|---|"]
        for cid, title, roles, result, note in self.results:
            lines.append("| %s | %s | %s | %s | %s |" % (cid, title, roles, result, note.replace("|", "/")))
        counts = {k: sum(1 for r in self.results if r[3] == k) for k in ('PASS', 'FAIL', 'N/A')}
        lines.append("")
        lines.append("PASS %(PASS)d · FAIL %(FAIL)d · N/A %(N/A)d" % counts)
        report = "\n".join(lines)
        _logger.info("UAT REPORT\n%s", report)
        try:
            out = pathlib.Path(odoo.tools.config['screenshots'])
            out.mkdir(parents=True, exist_ok=True)
            (out / 'uat_report.md').write_text(report, encoding='utf-8')
        except OSError as error:                                  # noqa: BLE001
            _logger.warning("UAT report not written: %s", error)
        failed = [r for r in self.results if r[3] == 'FAIL']
        self.assertFalse(failed, "UAT cases failed:\n" + "\n".join(
            "  %s %s - %s" % (r[0], r[1], r[4]) for r in failed))
