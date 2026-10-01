"""Owner spec 02/10/2026: the services and their heads.

Only Customer Service opens a file, and its head approves the opening
before any work starts; its head also closes a billed file for good.
A cost is approved by the head of the service that keyed it, and by no
other head. The names changed too - Manager became Head of Service -
but a name is not a rule, and these tests are about the rules.
"""

import json

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOwnerSpec0210(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.engaged = Account.create({
            'code': 'R4716', 'name': "Debours engages",
            'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({
            'code': 'R70621', 'name': "Fees", 'account_type': 'income'})
        cls.under = Account.create({
            'code': 'R65821', 'name': "Undercharge", 'account_type': 'expense'})
        cls.over = Account.create({
            'code': 'R75821', 'name': "Overcharge", 'account_type': 'income'})
        cls.sale_journal = env['account.journal'].create({
            'name': "Sales roles", 'type': 'sale', 'code': 'RSALS'})
        company.write({
            'clearance_oop_account_id': cls.engaged.id,
            'clearance_fee_account_id': cls.fee.id,
            'clearance_commission_account_id': cls.fee.id,
            'clearance_service_fee_account_id': cls.fee.id,
            'clearance_oop_undercharge_account_id': cls.under.id,
            'clearance_oop_overcharge_account_id': cls.over.id,
            'clearance_sale_journal_id': cls.sale_journal.id,
            'clearance_expense_approver_ids': [(5, 0, 0)],
        })
        cls.cash = env['account.journal'].create({
            'name': "Cash roles", 'type': 'cash', 'code': 'RCSHS'})
        cls.client = env['res.partner'].create({
            'name': "Roles Client", 'is_company': True,
            'street': "BP 9 Douala", 'email': "roles@test.cm",
            'vat': "M000000000041A",
            'company_registry': "RC/DLA/2026/B/0041",
            'clearance_invoice_name': "ROLES CLIENT SARL"})
        cls.vendor = env['res.partner'].create({
            'name': "Terminal Roles", 'is_company': True, 'supplier_rank': 1})
        cls.category = env['logistics.expense.category'].create({
            'name': "Port roles", 'code': "R-PRT"})
        cls.service = env['logistics.service.type'].create({
            'name': "Roles test", 'code': "R-ROL", 'commission_rate': 2.0})

        def user(name, *groups):
            return env['res.users'].create({
                'name': name,
                'login': name.lower().replace(' ', '.') + "@roles.test",
                'group_ids': [(6, 0, [env.ref(
                    'elite_clearance.group_clearance_' + g).id
                    for g in groups])]})
        cls.cs_agent = user("CS Agent R", 'customer_service')
        cls.cs_head = user("CS Head R", 'customer_service_manager')
        cls.ops_agent = user("Ops Agent R", 'operations')
        cls.ops_head = user("Ops Head R", 'ops_manager')
        cls.transit_agent = user("Transit Agent R", 'transit')
        cls.transit_head = user("Transit Head R", 'transit_manager')
        cls.biller = user("Biller R", 'billing')
        cls.gm = user("GM R", 'manager')

    def _file(self, user=None):
        model = self.env['logistics.file']
        if user:
            model = model.with_user(user)
        file = model.create({
            'customs_regime': 'im4', 'partner_id': self.client.id,
            'service_type_id': self.service.id,
            'bl_awb_ref': "MEDUR000077",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'package_count': 12, 'weight_kg': 800.0,
            'not_containerised': True,
        })
        return self.env['logistics.file'].browse(file.id)

    def _expense(self, file, user, amount=50000):
        exp = self.env['logistics.expense'].with_user(user).create({
            'file_id': file.id, 'category_id': self.category.id,
            'description': "Handling", 'amount': amount})
        return self.env['logistics.expense'].browse(exp.id)

    def _tasks(self, user, kind):
        return self.env['clearance.task'].with_user(user).search(
            [('kind', '=', kind)])

    def _bus(self):
        queued = self.env.cr.precommit.data.get("bus.bus.values", [])
        return [row for row in queued
                if json.loads(row["message"])["type"] == 'elite_clearance.task']

    # =================================================================
    # 1. a file opened by an agent waits for the Head of Customer Service
    # =================================================================
    def test_01_work_waits_for_the_head_of_customer_service(self):
        file = self._file(user=self.cs_agent)
        self.assertEqual(file.opening_state, 'none')
        with self.assertRaises(UserError) as caught:
            file.with_user(self.cs_agent).action_start_work()
        self.assertIn("Head of Customer Service", str(caught.exception))

        file.with_user(self.cs_agent).action_request_opening()
        self.assertEqual(file.opening_state, 'requested')
        self.assertEqual(file.opening_requested_by_id, self.cs_agent)
        self.assertEqual(file.stage_owner, "Head of Customer Service")

        # it sits in the head's queue, and in nobody else's
        self.assertTrue(self._tasks(self.cs_head, 'file_open'))
        self.assertFalse(self._tasks(self.ops_head, 'file_open'))
        # and the head can open what the queue lists - a draft nobody
        # else sees
        self.assertTrue(file.with_user(self.cs_head).read(['name']))
        with self.assertRaises(AccessError):
            file.with_user(self.ops_head).read(['name'])

        # another head is not this head
        with self.assertRaises(UserError):
            file.with_user(self.ops_head).action_approve_opening()
        with self.assertRaises(UserError):
            file.with_user(self.gm).action_approve_opening()
        with self.assertRaises(UserError):
            file.with_user(self.cs_agent).action_start_work()

        file.with_user(self.cs_head).action_approve_opening()
        self.assertEqual(file.opening_state, 'approved')
        self.assertEqual(file.opening_approved_by_id, self.cs_head)
        self.assertFalse(self._tasks(self.cs_head, 'file_open'))
        file.with_user(self.cs_agent).action_start_work()
        self.assertEqual(file.state, 'in_progress')

    def test_02_a_refusal_says_why_and_the_agent_may_ask_again(self):
        file = self._file(user=self.cs_agent)
        file.with_user(self.cs_agent).action_request_opening()
        with self.assertRaises(UserError, msg="a refusal carries a reason"):
            file.with_user(self.cs_head).action_refuse_opening()
        file.with_user(self.cs_head).write(
            {'opening_note': "Wrong client - this is SONICAM's cargo."})
        file.with_user(self.cs_head).action_refuse_opening()
        self.assertEqual(file.opening_state, 'refused')
        self.assertIn("Opening refused", file.stage_detail)
        with self.assertRaises(UserError):
            file.with_user(self.cs_agent).action_start_work()
        file.with_user(self.cs_agent).action_request_opening()
        self.assertEqual(file.opening_state, 'requested')

    def test_03_the_request_rings_the_head_of_customer_service_only(self):
        file = self._file(user=self.cs_agent)
        before = len(self._bus())
        file.with_user(self.cs_agent).action_request_opening()
        sent = self._bus()[before:]
        heads = self.env['clearance.task']._kind_users('file_open')
        self.assertTrue(sent, "the Head of Customer Service is told")
        self.assertEqual(len(sent), len(heads - self.cs_agent),
                         "one message per Head of Customer Service and no "
                         "other head - the Head of Service Operations is "
                         "not in that group")

    def test_04_the_superuser_still_starts_work_without_asking(self):
        """Hooks, the importer and the suite's own fixtures are not
        people; the gate is for users."""
        file = self._file()
        file.action_start_work()
        self.assertEqual(file.state, 'in_progress')

    # =================================================================
    # 2. a cost is its own service's head's to approve
    # =================================================================
    def test_05_the_head_of_the_keying_service_approves(self):
        file = self._file()
        file.action_start_work()
        ops_cost = self._expense(file, self.ops_agent)
        cs_cost = self._expense(file, self.cs_agent)
        transit_cost = self._expense(file, self.transit_agent)
        self.assertEqual(ops_cost.originating_team, 'operations')
        self.assertEqual(cs_cost.originating_team, 'customer_service')
        self.assertEqual(transit_cost.originating_team, 'transit')

        ops_cost.with_user(self.ops_agent).action_submit()
        cs_cost.with_user(self.cs_agent).action_submit()
        transit_cost.with_user(self.transit_agent).action_submit()

        # each head's queue holds their own service's cost and no other
        self.assertEqual(self._tasks(self.ops_head, 'expense_approve')
                         .mapped('res_id'), [ops_cost.id])
        self.assertEqual(self._tasks(self.cs_head, 'expense_approve')
                         .mapped('res_id'), [cs_cost.id])
        self.assertEqual(self._tasks(self.transit_head, 'expense_approve')
                         .mapped('res_id'), [transit_cost.id])

        with self.assertRaises(UserError) as caught:
            ops_cost.with_user(self.cs_head).action_approve()
        self.assertIn("Service Operations", str(caught.exception))
        with self.assertRaises(UserError):
            ops_cost.with_user(self.transit_head).action_approve()
        with self.assertRaises(UserError):
            cs_cost.with_user(self.ops_head).action_approve()
        ops_cost.with_user(self.ops_head).action_approve()
        cs_cost.with_user(self.cs_head).action_approve()
        transit_cost.with_user(self.transit_head).action_approve()
        self.assertEqual(
            {ops_cost.state, cs_cost.state, transit_cost.state}, {'approved'})

        # the file's banner named the right head while it waited
        late = self._expense(file, self.transit_agent)
        late.with_user(self.transit_agent).action_submit()
        self.assertEqual(file.stage_owner, "Head of Service Transit")

    def test_06_a_cost_of_no_service_is_any_heads(self):
        """Keyed by an administrator or imported: nobody's service, so
        the rule before 02/10/2026 still applies - any head signs."""
        file = self._file()
        file.action_start_work()
        cost = self._expense(file, self.env.user)       # the test admin
        self.assertFalse(cost.originating_team)
        cost.action_submit()
        self.assertIn(cost.id, self._tasks(self.ops_head, 'expense_approve')
                      .mapped('res_id'))
        self.assertIn(cost.id, self._tasks(self.cs_head, 'expense_approve')
                      .mapped('res_id'))
        cost.with_user(self.transit_head).action_approve()
        self.assertEqual(cost.state, 'approved')

    def test_07_a_configured_approver_list_still_wins(self):
        file = self._file()
        file.action_start_work()
        cost = self._expense(file, self.ops_agent)
        cost.with_user(self.ops_agent).action_submit()
        self.env.company.clearance_expense_approver_ids = [(6, 0, self.gm.ids)]
        try:
            with self.assertRaises(UserError,
                                   msg="the list names the GM, not the head"):
                cost.with_user(self.ops_head).action_approve()
            cost.with_user(self.gm).action_approve()
            self.assertEqual(cost.state, 'approved')
        finally:
            self.env.company.clearance_expense_approver_ids = [(5, 0, 0)]

    def test_08_the_bell_rings_for_the_right_head_only(self):
        file = self._file()
        file.action_start_work()
        cost = self._expense(file, self.ops_agent)
        before = len(self._bus())
        cost.with_user(self.ops_agent).action_submit()
        sent = self._bus()[before:]
        ops_heads = self.env['res.users'].search([
            ('all_group_ids', 'in', self.env.ref(
                'elite_clearance.group_clearance_ops_manager').ids),
            ('share', '=', False)])
        self.assertTrue(sent, "the Head of Service Operations is told")
        self.assertEqual(len(sent), len(ops_heads - self.ops_agent),
                         "one message per Operations head, and nobody else")

    # =================================================================
    # 3. closing a billed file is the Head of Customer Service's
    # =================================================================
    def _billed(self):
        file = self._file()
        file.action_start_work()
        file.customs_fee_amount = 30000
        cost = self._expense(file, self.env.user)
        cost.action_submit()
        cost.action_approve()
        cost.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                    'vendor_id': self.vendor.id})
        cost.action_submit_settlement()
        cost.action_approve_settlement()
        cost.action_settle()
        file.action_close_operations()
        file.action_create_invoice()
        return file

    def test_09_the_head_of_customer_service_closes_not_the_biller(self):
        file = self._billed()
        self.assertFalse(self._tasks(self.cs_head, 'file_close'),
                         "not until the invoice is posted")
        file.invoice_id.action_post()
        self.assertEqual(file.stage_owner, "Head of Customer Service")
        self.assertEqual(self._tasks(self.cs_head, 'file_close')
                         .mapped('res_id'), [file.id])
        self.assertFalse(self._tasks(self.biller, 'file_close'))

        with self.assertRaises(UserError):
            file.with_user(self.biller).action_mark_complete()
        with self.assertRaises(UserError):
            file.with_user(self.ops_head).action_mark_complete()
        file.with_user(self.cs_head).action_mark_complete()
        self.assertEqual(file.state, 'done')
        self.assertFalse(self._tasks(self.cs_head, 'file_close'))

    def test_10_a_file_with_a_cost_still_to_bill_is_not_in_the_close_queue(self):
        file = self._billed()
        file.invoice_id.action_post()
        self.assertTrue(self._tasks(self.cs_head, 'file_close'))
        # a cost lands after the bill - through the reopen the Head of
        # Service Operations grants: the file is Billing's again, not
        # the head's
        self.env['logistics.file.reopen.wizard'].create({
            'file_id': file.id, 'target_state': 'in_progress',
            'reason': "The demurrage invoice arrived late."}).action_reopen()
        late = self._expense(file, self.env.user, 20000)
        late.action_submit()
        late.action_approve()
        late.write({'payment_mode': 'cash', 'journal_id': self.cash.id,
                    'vendor_id': self.vendor.id})
        late.action_submit_settlement()
        late.action_approve_settlement()
        late.action_settle()
        file.action_close_operations()
        self.assertFalse(self._tasks(self.cs_head, 'file_close'))
        with self.assertRaises(UserError):
            file.with_user(self.cs_head).action_mark_complete()

    def test_11_the_form_offers_each_role_its_own_buttons(self):
        view = self.env.ref('elite_clearance.logistics_file_view_form')

        def arch(user):
            return self.env['logistics.file'].with_user(user).get_view(
                view.id)['arch']
        agent = arch(self.cs_agent)
        self.assertIn('action_request_opening', agent)
        self.assertNotIn('action_approve_opening', agent)
        self.assertNotIn('action_mark_complete', agent)
        head = arch(self.cs_head)
        self.assertIn('action_approve_opening', head)
        self.assertIn('action_refuse_opening', head)
        self.assertIn('action_mark_complete', head)
        self.assertNotIn('action_mark_complete', arch(self.biller))
        self.assertNotIn('action_approve_opening', arch(self.ops_head))
