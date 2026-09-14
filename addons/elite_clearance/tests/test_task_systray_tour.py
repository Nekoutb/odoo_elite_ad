import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestTaskSystrayTour(HttpCase):
    """The bell at the top right, in a real browser.

    Drives static/tests/tours/task_systray_tour.js as an Operations
    Manager with one disbursement waiting: the count shows, the list
    opens, and clicking the row lands on the expense itself rather than
    on a list to search through. A systray component that throws takes
    the whole top of everybody's screen with it, and no ORM-level test
    would ever see that.
    """

    def test_01_the_bell_counts_and_clicks_through_to_the_task(self):
        env = self.env
        client = env['res.partner'].create({
            'name': "Systray Client", 'is_company': True,
            'street': "BP 4321 Douala", 'email': "systray@test.cm",
            'vat': "M000000000021A",
            'company_registry': "RC/DLA/2026/B/0021",
            'clearance_invoice_name': "SYSTRAY CLIENT SARL"})
        category = env['logistics.expense.category'].create({
            'name': "Systray terminal fees", 'code': "T-SYS"})
        service = env['logistics.service.type'].create({
            'name': "Systray service", 'code': "T-SYS"})
        file = env['logistics.file'].create({
            'customs_regime': 'im4',
            'bl_awb_ref': "MEDUW000099",
            'goods_description': "Marchandises diverses",
            'cargo_value': 1000000.0,
            'partner_id': client.id, 'service_type_id': service.id})
        file.state = 'in_progress'
        expense = env['logistics.expense'].create({
            'file_id': file.id, 'category_id': category.id,
            'description': "Systray handling", 'amount': 25000})
        expense.action_submit()
        self.assertEqual(expense.state, 'submitted')

        login = "ops.manager.systray@clearance.test"
        env['res.users'].create({
            'name': "Ops Manager Systray", 'login': login, 'password': login,
            'group_ids': [(6, 0, [env.ref(
                'elite_clearance.group_clearance_ops_manager').id])]})

        self.start_tour("/odoo", "elite_clearance_task_systray", login=login)

    def test_02_a_landed_task_is_pushed_to_the_people_who_can_act_on_it(self):
        """The bus message, without a browser: who is told, and who is not."""
        env = self.env
        manager = env['res.users'].create({
            'name': "Ops Manager Bus", 'login': "ops.bus@clearance.test",
            'group_ids': [(6, 0, [env.ref(
                'elite_clearance.group_clearance_ops_manager').id])]})
        biller = env['res.users'].create({
            'name': "Biller Bus", 'login': "billing.bus@clearance.test",
            'group_ids': [(6, 0, [env.ref(
                'elite_clearance.group_clearance_billing').id])]})
        told = env['clearance.task']._kind_users('expense_approve')
        self.assertIn(manager, told)
        self.assertNotIn(biller, told, "Billing does not approve disbursements")
        told = env['clearance.task']._kind_users('billing')
        self.assertIn(biller, told)

        # The bus rows are queued on the cursor and only written at
        # commit, which a test never reaches - so the queue itself is what
        # there is to read, filtered to our own type because a chatter
        # post puts its own notifications in the same list.
        category = env['logistics.expense.category'].create({
            'name': "Bus fees", 'code': "T-BUS"})
        service = env['logistics.service.type'].create({
            'name': "Bus service", 'code': "T-BUS"})
        client = env['res.partner'].create({
            'name': "Bus Client", 'is_company': True})
        file = env['logistics.file'].create({
            'customs_regime': 'im4', 'bl_awb_ref': "MEDUW000098",
            'goods_description': "Marchandises diverses",
            'cargo_value': 500000.0,
            'partner_id': client.id, 'service_type_id': service.id})
        file.state = 'in_progress'
        expense = env['logistics.expense'].create({
            'file_id': file.id, 'category_id': category.id,
            'description': "Bus handling", 'amount': 1000})

        def ours():
            queued = env.cr.precommit.data.get("bus.bus.values", [])
            return [row for row in queued
                    if json.loads(row["message"])["type"]
                    == 'elite_clearance.task']

        expense.action_submit()
        sent = ours()
        recipients = env['clearance.task']._kind_users(
            'expense_approve').filtered(lambda user: user != env.user)
        self.assertTrue(sent, "somebody is told a disbursement is waiting")
        self.assertEqual(len(sent), len(recipients),
                         "one message each, and no more")

        # the person who did it is never told: a beep for your own click
        # teaches people to ignore beeps
        before = len(sent)
        env['clearance.task']._notify_assignment(
            'expense_approve', expense, users=manager | env.user)
        self.assertEqual(len(ours()) - before, 1,
                         "the manager, and not the person who pressed it")
