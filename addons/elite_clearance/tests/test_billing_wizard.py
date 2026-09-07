from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBillingWizard(TransactionCase):
    """The billing screen: what it proposes, and what it refuses."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'X4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.commission = Account.create({
            'code': 'X70621', 'name': "Commission", 'account_type': 'income'})
        cls.service_fee = Account.create({
            'code': 'X70622', 'name': "HAD", 'account_type': 'income'})
        cls.undercharge = Account.create({
            'code': 'X65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.overcharge = Account.create({
            'code': 'X75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.other_income = Account.create({
            'code': 'X70699', 'name': "Other clearance income",
            'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales", 'type': 'sale', 'code': 'XSAL6'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.commission.id,
            'clearance_commission_account_id': cls.commission.id,
            'clearance_service_fee_account_id': cls.service_fee.id,
            'clearance_oop_undercharge_account_id': cls.undercharge.id,
            'clearance_oop_overcharge_account_id': cls.overcharge.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash", 'type': 'cash', 'code': 'XCSH6'})
        cls.client = env['res.partner'].create({
            'name': "Wizard Client", 'is_company': True, 'street': "BP 1234 Douala", 'email': "client@test.cm", 'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal SA", 'is_company': True, 'street': "BP 1234 Douala", 'email': "client@test.cm", 'vat': "M000000000001A", 'company_registry': "RC/DLA/2026/B/0001", 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port", 'code': "T-PRT6"})
        cls.service = env['logistics.service.type'].create({
            'name': "Wizard test", 'code': "T-WIZ", 'commission_rate': 2.0})
        cls.file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW000001",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': cls.client.id, 'service_type_id': cls.service.id})
        cls.file.state = 'in_progress'
        cls.file.customs_fee_amount = 30000

        def user(name, group):
            return env['res.users'].create({
                'name': name, 'login': name.lower().replace(' ', '.') + "@wiz.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + group).id])]})
        cls.ops_manager = user("Ops Mgr W", 'ops_manager')
        cls.general_manager = user("Gen Mgr W", 'manager')

        for amount in (60000, 40000):
            exp = env['logistics.expense'].create({
                'file_id': cls.file.id, 'category_id': cls.category.id,
                'description': "Handling %d" % amount, 'amount': amount})
            exp.action_submit()
            exp.action_approve()
            exp.write({'payment_mode': 'cash', 'journal_id': cls.cash.id,
                       'vendor_id': cls.vendor.id})
            exp.action_submit_settlement()
            exp.action_approve_settlement()
            exp.action_settle()
        cls.file.action_close_operations()

    def _wizard(self):
        return self.env['logistics.billing.wizard'].with_context(
            active_id=self.file.id).create({})

    # ------------------------------------------------------------------
    def test_01_the_file_reads_ok_for_billing(self):
        self.assertEqual(self.file.state, 'ops_closed')
        label = dict(self.file._fields['state'].selection)['ops_closed']
        self.assertEqual(label, "OK for Billing")

    def test_02_the_screen_proposes_what_was_disbursed_and_the_two_services(self):
        wizard = self._wizard()
        self.assertEqual(len(wizard.debours_line_ids), 2)
        self.assertEqual(wizard.debours_engaged_total, 100000)
        self.assertEqual(wizard.debours_recharged_total, 100000,
                         "proposed at cost until somebody changes it")
        self.assertEqual(wizard.debours_variance, 0)
        self.assertFalse(wizard.needs_review)
        # the commission and the customs fee are parameters, not rows:
        # the agent sets a rate and a figure and watches the total move
        self.assertFalse(wizard.service_line_ids,
                         "the list is for ADDITIONAL services only")
        self.assertEqual(wizard.commission_rate, 2.0)
        self.assertEqual(wizard.commission_amount, 2000)
        self.assertEqual(wizard.customs_fee_amount, 30000)
        names = [line['name']
                 for line in wizard._service_lines_for_invoice()]
        self.assertTrue(any("Commission sur débours" in n for n in names), names)
        self.assertTrue(any("Honoraires Agréés en Douane" in n for n in names), names)
        self.assertEqual(wizard.service_total, 2000 + 30000)
        self.assertEqual(wizard.invoice_total, 132000)

    def test_03_billing_at_cost_needs_no_approval(self):
        wizard = self._wizard()
        wizard.action_create_invoice()
        invoice = self.file.invoice_id
        self.assertTrue(invoice)
        debours = invoice.invoice_line_ids.filtered(
            lambda l: l.account_id == self.engaged)
        self.assertEqual(sum(debours.mapped('price_subtotal')), 100000)
        self.assertFalse(invoice.invoice_line_ids.filtered(
            lambda l: l.account_id in (self.undercharge, self.overcharge)))

    def test_04_the_biller_may_add_a_service_line(self):
        wizard = self._wizard()
        wizard.service_line_ids = [(0, 0, {
            'name': "Frais de dossier", 'amount': 5000,
            'account_id': self.other_income.id})]
        self.assertEqual(wizard.service_total, 2000 + 30000 + 5000)
        wizard.action_create_invoice()
        extra = self.file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.account_id == self.other_income)
        self.assertEqual(extra.price_subtotal, 5000)
        self.assertEqual(extra.name, "Frais de dossier")

    def test_05_lowering_a_recharge_forces_a_review(self):
        """The biller may change the figure, but not decide it alone."""
        wizard = self._wizard()
        wizard.debours_line_ids[0].amount_recharged = 45000   # was 60,000
        self.assertEqual(wizard.debours_variance, -15000)
        self.assertTrue(wizard.needs_review)
        self.assertEqual(wizard.debours_line_ids[0].variance, -15000)
        with self.assertRaises(UserError):
            wizard.action_create_invoice()
        with self.assertRaises(UserError):
            wizard.action_submit_for_review()          # no reason yet
        wizard.review_reason = "Client disputed the terminal charge."
        wizard.action_submit_for_review()
        self.assertEqual(self.file.recharge_amount, 85000)
        self.assertEqual(self.file.recharge_state, 'requested')
        self.assertFalse(self.file.invoice_id, "no invoice from a review")
        # and the intent is recorded on the disbursement itself
        self.assertEqual(
            self.file._billable_expenses().filtered(
                lambda e: e.amount == 60000).recharge_amount, 45000)

    def test_06_after_both_approvals_the_screen_bills_the_shortfall(self):
        wizard = self._wizard()
        wizard.debours_line_ids[0].amount_recharged = 45000
        wizard.review_reason = "Client disputed the terminal charge."
        wizard.action_submit_for_review()
        self.env['ir.attachment'].create({
            'name': "agreement.pdf", 'res_model': 'logistics.file',
            'res_id': self.file.id, 'raw': b"dummy"})
        self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.file.with_user(self.general_manager).action_approve_recharge_gm()
        self.assertEqual(self.file.recharge_state, 'approved')

        again = self._wizard()
        self.assertEqual(again.debours_recharged_total, 85000,
                         "the screen reopens on the approved figures")
        self.assertFalse(again.needs_review, "the approval stands")
        again.action_create_invoice()
        lines = self.file.invoice_id.invoice_line_ids
        self.assertEqual(
            sum(lines.filtered(lambda l: l.account_id == self.engaged)
                .mapped('price_subtotal')), 100000,
            "47xx still clears at cost")
        under = lines.filtered(lambda l: l.account_id == self.undercharge)
        self.assertEqual(under.price_subtotal, -15000)
        # The commission follows what the client is CHARGED, not what was
        # disbursed: 2% of 85,000, not of 100,000. The billing screen shows
        # the rate beside the recharged total and recomputes as either
        # moves, so the biller sees the figure they are agreeing to.
        # (Owner: confirm. Basing it on cost instead is a one-line change.)
        self.assertEqual(
            sum(lines.filtered(lambda l: l.display_type == 'product')
                .mapped('price_subtotal')),
            85000 + 1700 + 30000)

    def test_07_raising_a_recharge_also_goes_for_review(self):
        wizard = self._wizard()
        wizard.debours_line_ids[0].amount_recharged = 70000
        self.assertEqual(wizard.debours_variance, 10000)
        self.assertTrue(wizard.needs_review)
        wizard.review_reason = "Agreed uplift on the terminal charge."
        wizard.action_submit_for_review()
        self.assertEqual(self.file.recharge_state, 'requested')
        # above cost, Operations alone releases it
        self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.assertEqual(self.file.recharge_state, 'approved')
        self._wizard().action_create_invoice()
        over = self.file.invoice_id.invoice_line_ids.filtered(
            lambda l: l.account_id == self.overcharge)
        self.assertEqual(over.price_subtotal, 10000)

    # ------------------------------------------------------------------
    # Who is offered the screen, and who can use it. The button, the
    # action, the wizard's access rule and the task queue must all name
    # the same department. On 06/09/2026 the buttons still said Finance
    # while everything else said Billing: the dialog was gone for the
    # people meant to use it and refused the people who could see it.
    # Unit tests run as admin, who is in every group, so only a look at
    # the form as the restricted user catches that.
    def _form_arch(self, user):
        view = self.env.ref('elite_clearance.logistics_file_view_form')
        return self.env['logistics.file'].with_user(user).get_view(
            view.id)['arch']

    def _user(self, name, group):
        return self.env['res.users'].create({
            'name': name, 'login': name.lower().replace(' ', '.') + "@wiz.test",
            'group_ids': [(6, 0, [self.env.ref(
                'elite_clearance.group_clearance_' + group).id])]})

    def test_20_a_billing_agent_is_offered_the_screen_and_can_bill(self):
        biller = self._user("Bill Agent W", 'billing')
        arch = self._form_arch(biller)
        self.assertIn('action_open_billing', arch,
                      "the Billing button is stripped from the form")
        self.assertIn('action_request_reopen_imported', arch)
        self.assertIn('action_mark_complete', arch)
        self.assertIn('invoices_posted', arch,
                      "Mark Complete waits for every invoice of the bill")
        self.assertIn('bill_stands', arch)
        action = self.file.with_user(biller).action_open_billing()
        self.assertEqual(action['res_model'], 'logistics.billing.wizard')
        # and the screen works end to end AS THAT USER: the write-through
        # to the customer record and the invoice itself both need rights
        # the group must carry
        wizard = self.env['logistics.billing.wizard'].with_user(biller) \
            .with_context(active_id=self.file.id).create({
                'client_email': "billing@wizard-client.cm"})
        wizard.action_create_invoice()
        self.assertTrue(self.file.invoice_id)
        self.assertEqual(self.file.invoice_id.create_uid, biller)
        self.assertEqual(self.client.email, "billing@wizard-client.cm")

    def test_21_a_finance_agent_is_not_offered_what_would_be_refused(self):
        finance = self._user("Fin Agent W", 'finance')
        arch = self._form_arch(finance)
        self.assertNotIn('action_open_billing', arch,
                         "Finance is shown a button the action refuses")
        self.assertNotIn('action_request_reopen_imported', arch)
        self.assertNotIn('action_mark_complete', arch)
        with self.assertRaises(UserError):
            self.file.with_user(finance).action_open_billing()
        with self.assertRaises(AccessError):
            self.env['logistics.billing.wizard'].with_user(finance) \
                .with_context(active_id=self.file.id).create({})

    def test_22_a_cancelled_invoice_hands_the_file_back_to_billing(self):
        self._wizard().action_create_invoice()
        first = self.file.invoice_id
        Task = self.env['clearance.task']
        queue = [('kind', '=', 'billing'), ('file_id', '=', self.file.id)]
        self.assertFalse(Task.search(queue), "billed: out of the queue")
        first.button_cancel()
        self.assertEqual(self.file.invoice_state, 'cancel')
        self.assertTrue(Task.search(queue),
                        "a cancelled invoice puts the file back in the queue")
        self._wizard().action_create_invoice()
        self.assertNotEqual(self.file.invoice_id, first)
        self.assertEqual(self.file.invoice_id.state, 'draft')

    def test_23_a_file_opened_before_the_rule_completes_its_shipment_at_billing(self):
        """The shipment essentials became mandatory on 06/09/2026. A file
        opened before that, or reopened from Teese, reaches billing with
        them blank - and must be able to complete them there rather than
        being stuck behind a form that will not save."""
        old = self.env['logistics.file'].with_context(legacy_import=True).create({
            'customs_regime': 'im4', 'customs_fee_amount': 30000,
            'partner_id': self.client.id, 'service_type_id': self.service.id})
        old.with_context(legacy_import=True).write({'state': 'ops_closed'})
        self.assertFalse(old.bl_awb_ref)
        wizard = self.env['logistics.billing.wizard'].with_context(
            active_id=old.id).create({})
        self.assertTrue(wizard.shipment_details_missing)
        with self.assertRaises(UserError) as caught:
            wizard.action_create_invoice()
        self.assertIn("N° BL / N° LTA", str(caught.exception))
        self.assertIn("Valeur RVC", str(caught.exception))
        # half an answer is refused in billing words, not opening words
        wizard.shipment_bl_awb_ref = "MEDUW000002"
        with self.assertRaises(ValidationError) as caught:
            wizard.action_create_invoice()
        self.assertIn("cannot be invoiced", str(caught.exception))
        wizard.write({'shipment_bl_awb_ref': "MEDUW000002",
                      'shipment_goods': "Carreaux",
                      'shipment_cargo_value': 500000})
        self.assertFalse(wizard.shipment_details_missing)
        wizard.action_create_invoice()
        self.assertEqual(old.bl_awb_ref, "MEDUW000002")
        self.assertEqual(old.goods_description, "Carreaux")
        self.assertEqual(old.cargo_value, 500000)
        self.assertTrue(old.invoice_id)

    # ------------------------------------------------------------------
    # A split bill (owner 07/09/2026): the disbursements on one invoice,
    # the services on another, each printed as the usual document.
    def test_30_the_bill_can_be_split_in_two(self):
        wizard = self._wizard()
        wizard.split_invoices = True
        self.assertEqual(wizard.split_debours_total, 100000)
        self.assertEqual(wizard.split_services_total, 32000)
        action = wizard.action_create_invoice()
        self.assertEqual(action['res_model'], 'account.move')
        self.assertNotIn('res_id', action, "two invoices open as a list")
        debours = self.file.debours_invoice_id
        services = self.file.invoice_id
        self.assertTrue(debours and services and debours != services)
        self.assertEqual(debours.clearance_invoice_kind, 'debours')
        self.assertEqual(services.clearance_invoice_kind, 'services')
        self.assertEqual(debours.logistics_file_id, self.file)
        self.assertEqual(services.logistics_file_id, self.file)
        self.assertEqual(self.file.invoice_count, 2)
        self.assertEqual(self.file._client_invoices(), debours | services)
        # the disbursements invoice: at cost, and no VAT anywhere on it
        products = debours.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product')
        self.assertEqual(set(products.mapped('clearance_category')), {'debours'})
        self.assertFalse(products.mapped('tax_ids'))
        self.assertEqual(debours.amount_tax, 0)
        self.assertEqual(debours.amount_total, 100000)
        self.assertEqual(
            sum(products.filtered(lambda l: l.account_id == self.engaged)
                .mapped('price_subtotal')), 100000, "47xx clears in full")
        # the services invoice: the commission and the fee, nothing else
        products = services.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product')
        self.assertEqual(set(products.mapped('clearance_category')),
                         {'prestation'})
        self.assertEqual(services.amount_untaxed, 2000 + 30000)
        self.assertFalse(products.filtered(
            lambda l: l.account_id == self.engaged))
        self.assertNotEqual(debours.name, services.name,
                            "two numbers, one after the other")
        # billed is billed: no third invoice, and completion wants both
        with self.assertRaises(UserError):
            self._wizard().action_create_invoice()
        self.assertTrue(self.file.bill_stands)
        self.assertFalse(self.file.invoices_posted)
        with self.assertRaises(UserError):
            self.file.action_mark_complete()
        services.action_post()
        self.assertFalse(self.file.invoices_posted, "both, not one")
        with self.assertRaises(UserError):
            self.file.action_mark_complete()
        debours.action_post()
        self.assertTrue(self.file.invoices_posted)
        self.file.action_mark_complete()
        self.assertEqual(self.file.state, 'done')

    def test_34_a_cancelled_half_is_issued_again_on_its_own(self):
        """A split bill is one bill. Cancel one half and the file is not
        billed: Mark Complete refuses, the file is back in Billing's queue,
        and the screen issues that half again - the other one, posted or
        not, stands untouched."""
        Task = self.env['clearance.task']
        queue = [('kind', '=', 'billing'), ('file_id', '=', self.file.id)]
        wizard = self._wizard()
        wizard.split_invoices = True
        wizard.action_create_invoice()
        services, debours = self.file.invoice_id, self.file.debours_invoice_id
        self.assertFalse(Task.search(queue))
        services.action_post()
        debours.button_cancel()
        self.assertFalse(self.file.bill_stands)
        self.assertFalse(self.file.invoices_posted)
        with self.assertRaises(UserError):
            self.file.action_mark_complete()
        self.assertTrue(Task.search(queue), "half a bill is not a bill")
        self.assertEqual(self.file._standing_half(), services)
        again = self._wizard()
        self.assertEqual(again.reissue_kind, 'debours')
        self.assertEqual(again.standing_invoice_id, services)
        self.assertTrue(again.split_invoices, "forced while a half stands")
        action = again.action_create_invoice()
        self.assertEqual(self.file.invoice_id, services,
                         "the posted half keeps its number and its lines")
        reissued = self.file.debours_invoice_id
        self.assertNotEqual(reissued, debours)
        self.assertEqual(reissued.clearance_invoice_kind, 'debours')
        self.assertEqual(reissued.amount_total, 100000)
        self.assertEqual(action.get('res_id'), reissued.id,
                         "one invoice was issued, so it opens directly")
        self.assertTrue(self.file.bill_stands)
        self.assertFalse(Task.search(queue))
        self.assertEqual(self.file.invoice_count, 3,
                         "the cancelled one stays on record")
        reissued.action_post()
        self.file.action_mark_complete()
        self.assertEqual(self.file.state, 'done')

    def test_34b_a_billed_invoice_is_cancelled_never_deleted(self):
        """Every gate reads the file's two pointers, so a deleted half
        would leave the survivor reading as the whole bill."""
        wizard = self._wizard()
        wizard.split_invoices = True
        wizard.action_create_invoice()
        debours = self.file.debours_invoice_id
        debours.button_cancel()
        with self.assertRaises(UserError):
            debours.unlink()
        self.assertTrue(debours.exists())
        self.assertFalse(self.file.bill_stands, "the half is still missing")
        with self.assertRaises(UserError):
            self.file.invoice_id.unlink()

    def test_34c_the_standing_half_cannot_be_re_negotiated(self):
        """Only the missing half is issued, so a change to the standing
        side would be recorded on the file and printed nowhere."""
        wizard = self._wizard()
        wizard.split_invoices = True
        wizard.action_create_invoice()
        services = self.file.invoice_id
        self.file.debours_invoice_id.button_cancel()
        again = self._wizard()
        self.assertEqual(again.reissue_kind, 'debours')
        again.customs_fee_amount = 45000          # the standing side
        with self.assertRaises(UserError) as caught:
            again.action_create_invoice()
        self.assertIn(services.name, str(caught.exception))
        self.assertEqual(self.file.customs_fee_amount, 30000,
                         "the frozen side is not recorded either")
        again.customs_fee_amount = 30000
        again.action_create_invoice()
        self.assertEqual(self.file.invoice_id, services)
        self.assertEqual(self.file.debours_invoice_id.amount_total, 100000)

    def test_35_the_services_half_can_be_issued_again_too(self):
        wizard = self._wizard()
        wizard.split_invoices = True
        wizard.action_create_invoice()
        services, debours = self.file.invoice_id, self.file.debours_invoice_id
        debours.action_post()
        services.button_cancel()
        again = self._wizard()
        self.assertEqual(again.reissue_kind, 'services')
        self.assertEqual(again.standing_invoice_id, debours)
        again.action_create_invoice()
        self.assertEqual(self.file.debours_invoice_id, debours)
        self.assertNotEqual(self.file.invoice_id, services)
        self.assertEqual(self.file.invoice_id.clearance_invoice_kind, 'services')
        self.assertEqual(self.file.invoice_id.amount_untaxed, 32000)
        self.assertTrue(self.file.bill_stands)
        # and the whole bill can be cancelled and issued as ONE invoice
        self.file.invoice_id.button_cancel()
        debours.button_draft()
        debours.button_cancel()
        self.assertFalse(self.file.bill_stands)
        once = self._wizard()
        self.assertFalse(once.reissue_kind)
        once.split_invoices = False
        once.action_create_invoice()
        self.assertEqual(self.file.invoice_id.clearance_invoice_kind, 'full')
        self.assertFalse(self.file.debours_invoice_id)
        self.assertFalse(self.file.billing_split)

    def test_31_a_split_bill_carries_the_shortfall_on_the_disbursements_side(self):
        wizard = self._wizard()
        wizard.split_invoices = True
        wizard.debours_line_ids[0].amount_recharged = 45000
        wizard.review_reason = "Client disputed the terminal charge."
        wizard.action_submit_for_review()
        self.assertTrue(self.file.billing_split, "the choice is recorded")
        self.env['ir.attachment'].create({
            'name': "agreement.pdf", 'res_model': 'logistics.file',
            'res_id': self.file.id, 'raw': b"dummy"})
        self.file.with_user(self.ops_manager).action_approve_recharge_ops()
        self.file.with_user(self.general_manager).action_approve_recharge_gm()
        again = self._wizard()
        self.assertTrue(again.split_invoices,
                        "Resume Billing issues what was asked for")
        again.action_create_invoice()
        debours = self.file.debours_invoice_id
        lines = debours.invoice_line_ids
        self.assertEqual(
            sum(lines.filtered(lambda l: l.account_id == self.engaged)
                .mapped('price_subtotal')), 100000, "47xx still clears at cost")
        self.assertEqual(
            lines.filtered(lambda l: l.account_id == self.undercharge)
            .price_subtotal, -15000)
        self.assertEqual(debours.amount_total, 85000,
                         "the client is charged what was agreed")
        services = self.file.invoice_id
        self.assertFalse(services.invoice_line_ids.filtered(
            lambda l: l.account_id in (self.undercharge, self.engaged)))
        self.assertEqual(services.amount_untaxed, 1700 + 30000)

    def test_32_a_split_needs_something_on_both_sides(self):
        wizard = self._wizard()
        wizard.split_invoices = True
        wizard.commission_rate = 0
        wizard.customs_fee_amount = 0
        with self.assertRaises(UserError):
            wizard.action_create_invoice()
        self.assertFalse(self.file.invoice_id)
        self.assertFalse(self.file.debours_invoice_id)

    def test_33_each_document_of_a_split_bill_deducts_its_own_advances(self):
        """An advance on the HAD/DAU is an advance on the services; other
        advances are funds put up for the disbursements. The file's
        balance due still nets everything."""
        wizard = self._wizard()
        wizard.split_invoices = True
        wizard.advance_had_amount = 5000
        wizard.advance_other_amount = 20000
        wizard.action_create_invoice()
        debours, services = self.file.debours_invoice_id, self.file.invoice_id
        self.assertEqual(debours._clearance_advances(), (None, None, 20000))
        self.assertEqual(services._clearance_advances(), (5000, 0.0, None))
        self.assertEqual(debours._clearance_advance_total(), 20000)
        self.assertEqual(services._clearance_advance_total(), 5000)
        self.assertFalse(debours._clearance_prints_vat())
        self.assertTrue(services._clearance_prints_vat())
        self.assertEqual(self.file.invoice_balance_due,
                         100000 + 32000 - 25000)
        action = self.file.action_preview_invoice()
        self.assertEqual(sorted(action['context']['active_ids']),
                         sorted((debours | services).ids),
                         "Preview shows both documents")
