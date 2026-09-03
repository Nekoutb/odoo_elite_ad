import base64
import csv
import io
import zipfile

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

# Column headers exactly as the warehouse export writes them.
HEADERS = {
    'wh_dim_partner.csv': "id,tenant_id,odoo_id,name,ref,is_company,write_date",
    'wh_fact_dossier.csv': ("id,tenant_id,odoo_id,code,partner_odoo_id,client_name,type_name,port_name,"
                            "employee_name,opened_date,closed_date,billing_start_date,suspended_date,"
                            "is_closed,is_suspended,lead_days,billing_lag_days,weight_kg,containers,"
                            "packages,cargo_value,regime,incoterm,embarquement,importer,write_date"),
    'wh_fact_invoice.csv': ("id,tenant_id,odoo_id,name,move_type,state,payment_state,voyage_type,"
                            "invoice_date,invoice_date_due,sent_date,deposited_date,receipt_date,"
                            "partner_odoo_id,journal_odoo_id,dossier_odoo_id,amount_untaxed,"
                            "amount_total,amount_residual,write_date"),
    'wh_fact_invoice_line.csv': ("id,tenant_id,odoo_id,move_odoo_id,account_odoo_id,product_odoo_id,"
                                 "invoice_date,move_type,quantity,price_unit,discount,price_subtotal,"
                                 "is_debours,label,write_date"),
    'wh_fact_advance.csv': ("id,tenant_id,odoo_id,dossier_odoo_id,supplier_name,label,amount,"
                            "requested_date,disbursed_date,disbursement_lag_days,is_justified,write_date"),
    'wh_fact_validation.csv': ("id,tenant_id,odoo_id,doc_key,doc_type,circuit,rang,doc_date,"
                               "step_date,step_lag_days,total_days,is_passed,write_date"),
}
SYNC_HEADER = "id,tenant_id,model,last_write_date,last_id,last_run_at,rows_synced,last_error,created_at,updated_at"
W = "2026-08-26 21:24:07"


def _csv(name, rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=HEADERS[name].split(","))
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    return out.getvalue()


def build_zip(after_cutoff=False):
    """A miniature of the real export exercising every judgement call."""
    partners = [
        {'id': 1, 'tenant_id': 23, 'odoo_id': 1, 'name': "ELIMELEC SARL", 'ref': "CLT26001", 'is_company': 1, 'write_date': W},
        {'id': 2, 'tenant_id': 23, 'odoo_id': 2, 'name': "PIZZAROTI", 'ref': "CLT26002", 'is_company': 1, 'write_date': W},
    ]
    dossiers = [
        # a normal import dossier, whose number our IM sequence must jump past
        {'id': 1, 'tenant_id': 23, 'odoo_id': 8001, 'code': "2026IM0007", 'partner_odoo_id': 2, 'client_name': "PIZZAROTI",
         'type_name': "MISE A LA CONSOMMATION", 'port_name': "KRIBI", 'employee_name': "FOKAM Ravie",
         'opened_date': "2026-03-27", 'is_closed': 0, 'is_suspended': 0, 'weight_kg': "30.000", 'containers': 2,
         'packages': 40, 'cargo_value': "24860.00", 'regime': "EX1", 'incoterm': "CIF", 'embarquement': "CONTENEUR",
         'importer': "SODICAM", 'write_date': W},
        # duplicate code: must be imported, renamed
        {'id': 2, 'tenant_id': 23, 'odoo_id': 8002, 'code': "2026IM0007", 'partner_odoo_id': 1, 'client_name': "ELIMELEC SARL",
         'type_name': "AUTRE", 'port_name': "DOUALA", 'employee_name': "DG ELIMELEC",
         'opened_date': "2026-04-01", 'is_closed': 0, 'is_suspended': 0, 'write_date': W},
        # closed, no opening date, an export
        {'id': 3, 'tenant_id': 23, 'odoo_id': 8003, 'code': "2025EX0154", 'partner_odoo_id': 2, 'client_name': "PIZZAROTI",
         'type_name': "EXPORT STANDARD", 'port_name': "", 'employee_name': "FOKAM Ravie",
         'opened_date': "", 'closed_date': "2026-08-21", 'is_closed': 1, 'is_suspended': 0, 'write_date': W},
    ]
    advances = [
        {'id': 1, 'tenant_id': 23, 'odoo_id': 11001, 'dossier_odoo_id': 8001, 'supplier_name': "MAERSK", 'label': "Surestaries",
         'amount': "50000.00", 'requested_date': "2026-03-30", 'disbursed_date': "2026-03-31", 'disbursement_lag_days': 1, 'is_justified': 0, 'write_date': W},
        {'id': 2, 'tenant_id': 23, 'odoo_id': 11002, 'dossier_odoo_id': 8001, 'supplier_name': "DOUANE", 'label': "Liquidation douane",
         'amount': "200000.00", 'requested_date': "2026-04-01", 'disbursed_date': "2026-04-01", 'disbursement_lag_days': 0, 'is_justified': 1, 'write_date': W},
        # a reversal
        {'id': 3, 'tenant_id': 23, 'odoo_id': 11003, 'dossier_odoo_id': 8001, 'supplier_name': "MAERSK", 'label': "RETOUR - Surestaries",
         'amount': "-50000.00", 'requested_date': "2026-04-02", 'disbursed_date': "2026-04-02", 'disbursement_lag_days': 0, 'is_justified': 0, 'write_date': W},
        # no dossier at all
        {'id': 4, 'tenant_id': 23, 'odoo_id': 11004, 'dossier_odoo_id': "", 'supplier_name': "", 'label': "Timbre",
         'amount': "1000.00", 'requested_date': "2026-04-03", 'disbursed_date': "2026-04-03", 'disbursement_lag_days': 0, 'is_justified': 0, 'write_date': W},
    ]
    invoices = [
        {'id': 1, 'tenant_id': 23, 'odoo_id': 201, 'name': "EL26IM228", 'move_type': "out_invoice", 'state': "posted",
         'payment_state': "not_paid", 'invoice_date': "2026-03-26", 'invoice_date_due': "2026-04-02", 'partner_odoo_id': 2,
         'dossier_odoo_id': 8001, 'amount_untaxed': "52000.00", 'amount_total': "312010.00", 'amount_residual': "312010.00", 'write_date': W},
        # a credit note, exported with a negative total
        {'id': 2, 'tenant_id': 23, 'odoo_id': 202, 'name': "AV26IM001", 'move_type': "out_invoice", 'state': "posted",
         'payment_state': "paid", 'invoice_date': "2026-04-10", 'invoice_date_due': "2026-04-10", 'partner_odoo_id': 2,
         'dossier_odoo_id': 8001, 'amount_untaxed': "-10000.00", 'amount_total': "-10000.00", 'amount_residual': "0.00", 'write_date': W},
        # not tied to any dossier
        {'id': 3, 'tenant_id': 23, 'odoo_id': 203, 'name': "EL26ND045", 'move_type': "out_invoice", 'state': "posted",
         'payment_state': "partial", 'invoice_date': "2026-05-05", 'invoice_date_due': "2026-05-12", 'partner_odoo_id': 1,
         'dossier_odoo_id': "", 'amount_untaxed': "20000.00", 'amount_total': "23850.00", 'amount_residual': "3850.00", 'write_date': W},
    ]
    if after_cutoff:
        invoices.append(
            {'id': 4, 'tenant_id': 23, 'odoo_id': 204, 'name': "EL26IM900", 'move_type': "out_invoice", 'state': "posted",
             'payment_state': "not_paid", 'invoice_date': "2026-09-02", 'invoice_date_due': "2026-09-09", 'partner_odoo_id': 2,
             'dossier_odoo_id': 8001, 'amount_untaxed': "1000.00", 'amount_total': "1000.00", 'amount_residual': "1000.00", 'write_date': W})
    lines = [
        {'id': 1, 'tenant_id': 23, 'odoo_id': 1446, 'move_odoo_id': 201, 'product_odoo_id': 1449, 'invoice_date': "2026-03-26",
         'move_type': "out_invoice", 'quantity': "1.0000", 'price_unit': "52000.0000", 'discount': "0.0000",
         'price_subtotal': "52000.00", 'is_debours': 0, 'label': "Frais d'ouverture de dossier", 'write_date': W},
        {'id': 2, 'tenant_id': 23, 'odoo_id': 1447, 'move_odoo_id': 201, 'product_odoo_id': 1447, 'invoice_date': "2026-03-26",
         'move_type': "out_invoice", 'quantity': "1.0000", 'price_unit': "250000.0000", 'discount': "0.0000",
         'price_subtotal': "250000.00", 'is_debours': 1, 'label': "Liquidation douane", 'write_date': W},
        {'id': 3, 'tenant_id': 23, 'odoo_id': 1448, 'move_odoo_id': 202, 'product_odoo_id': 1449, 'invoice_date': "2026-04-10",
         'move_type': "out_invoice", 'quantity': "1.0000", 'price_unit': "-10000.0000", 'discount': "0.0000",
         'price_subtotal': "-10000.00", 'is_debours': 0, 'label': "Remise commerciale", 'write_date': W},
        {'id': 4, 'tenant_id': 23, 'odoo_id': 1449, 'move_odoo_id': 203, 'product_odoo_id': 5541, 'invoice_date': "2026-05-05",
         'move_type': "out_invoice", 'quantity': "1.0000", 'price_unit': "20000.0000", 'discount': "0.0000",
         'price_subtotal': "20000.00", 'is_debours': 1, 'label': "Droits de Douane", 'write_date': W},
    ]
    validations = [
        {'id': 1, 'tenant_id': 23, 'odoo_id': 18636, 'doc_key': 11001, 'doc_type': "Avance de frais", 'circuit': "Avance frais standard",
         'rang': 1, 'doc_date': "2026-03-30", 'step_date': "2026-03-30", 'step_lag_days': "0.007", 'total_days': "0.001", 'is_passed': 1, 'write_date': W},
    ]
    sync = SYNC_HEADER + "\n" + "9,23,erp:clients,,,2026-08-26 21:24:08,190,,2026-08-26 21:24:08,2026-08-26 21:24:08\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_manifest.txt", "Teese export - test fixture")
        z.writestr("_sync_state.csv", sync)
        z.writestr("wh_dim_partner.csv", _csv("wh_dim_partner.csv", partners))
        z.writestr("wh_fact_dossier.csv", _csv("wh_fact_dossier.csv", dossiers))
        z.writestr("wh_fact_advance.csv", _csv("wh_fact_advance.csv", advances))
        z.writestr("wh_fact_invoice.csv", _csv("wh_fact_invoice.csv", invoices))
        z.writestr("wh_fact_invoice_line.csv", _csv("wh_fact_invoice_line.csv", lines))
        z.writestr("wh_fact_validation.csv", _csv("wh_fact_validation.csv", validations))
    return buf.getvalue()


@tagged('post_install', '-at_install')
class TestLegacyImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        if not company.chart_template:
            env['account.chart.template'].try_loading('generic_coa', company)
        Account = env['account.account']
        cls.oop = Account.create({'code': 'X4719', 'name': "Debours engages",
                                  'account_type': 'asset_current', 'reconcile': True})
        cls.fee = Account.create({'code': 'X7069', 'name': "Fee income", 'account_type': 'income'})
        company.write({'clearance_oop_account_id': cls.oop.id, 'clearance_fee_account_id': cls.fee.id})
        cls.batch = cls.env['logistics.legacy.import'].create({
            'name': "fixture", 'zip_file': base64.b64encode(build_zip()),
            'zip_filename': "fixture.zip", 'cutoff_date': "2026-08-31"})

    def _file(self, legacy_id):
        return self.env['logistics.file'].search([('legacy_id', '=', legacy_id)])

    def test_01_full_run_maps_every_table(self):
        self.batch.action_import()
        self.assertEqual(self.batch.state, 'done', self.batch.log)
        self.assertEqual(self.batch.count_partners, 2)
        self.assertEqual(self.batch.count_files, 3)
        self.assertEqual(self.batch.count_expenses, 4)
        self.assertEqual(self.batch.count_invoices, 3)
        self.assertEqual(self.batch.count_lines, 4)
        self.assertEqual(self.batch.count_ports, 2)
        self.assertEqual(self.batch.count_employees, 2)
        self.assertEqual(self.batch.count_after_cutoff, 0)
        self.assertEqual(str(self.batch.export_synced_at)[:10], "2026-08-26")
        self.assertIn("predates the cutoff by 5 day(s)", self.batch.log)

        f = self._file(8001)
        self.assertEqual(f.name, "2026IM0007")
        self.assertEqual(f.service_type_id.code, "IM")
        self.assertEqual(f.port_id.name, "Kribi")
        self.assertEqual(f.employee_id.name, "FOKAM Ravie")
        self.assertEqual(f.shipment_type, 'container')
        self.assertEqual(f.container_count, 2)
        self.assertEqual(f.incoterm_id.code, "CIF")
        self.assertEqual(f.customs_regime, "EX1")
        self.assertEqual(f.legacy_type_name, "MISE A LA CONSOMMATION")
        self.assertEqual(f.state, 'in_progress')
        self.assertFalse(f.document_ids, "Historical files carry no checklist.")
        self.assertTrue(f.analytic_account_id)

    def test_02_duplicate_code_is_kept_and_renamed(self):
        self.batch.action_import()
        dup = self._file(8002)
        self.assertEqual(dup.name, "2026IM0007-8002")
        self.assertEqual(dup.service_type_id.code, "AU")
        self.assertIn("duplicate code 2026IM0007", self.batch.log)

    def test_03_closed_and_undated_dossier(self):
        self.batch.action_import()
        f = self._file(8003)
        self.assertEqual(f.state, 'done')
        self.assertEqual(str(f.date_closed), "2026-08-21")
        self.assertEqual(str(f.date_opened), "2025-01-01", "Year of the code when no date was exported.")
        self.assertEqual(f.service_type_id.code, "ES")
        self.assertFalse(f.port_id)

    def test_04_advances_become_legacy_expenses_outside_every_total(self):
        self.batch.action_import()
        f = self._file(8001)
        exps = f.expense_ids.sorted('legacy_id')
        self.assertEqual(len(exps), 3)
        self.assertTrue(all(e.is_legacy for e in exps))
        normal, justified, reversal = exps
        self.assertEqual(normal.state, 'settled')
        self.assertEqual(normal.vendor_id.name, "MAERSK")
        self.assertTrue(normal.vendor_id.supplier_rank)
        self.assertEqual(str(normal.date_requested), "2026-03-30")
        self.assertTrue(justified.legacy_justified)
        self.assertEqual(reversal.state, 'cancel')
        self.assertTrue(reversal.legacy_reversal)
        self.assertEqual(reversal.amount, 50000, "Kept with its absolute value.")
        self.assertFalse(normal.settlement_move_id, "History is not posted.")
        # the point: legacy money never feeds billing
        self.assertEqual(f.oop_total, 0)
        self.assertEqual(f.unjustified_advance_total, 0)
        park = self._file(-1)
        self.assertEqual(park.name, "LEGACY-UNALLOCATED")
        self.assertEqual(len(park.expense_ids), 1)
        self.assertEqual(park.expense_ids.description, "Timbre")

    def test_05_invoices_are_drafts_that_can_never_be_posted(self):
        """Billing done in Teese shows on the file and in Invoicing as a
        Draft customer invoice, greyed as imported, and posting is refused."""
        moves_before = self.env['account.move'].search_count([])
        self.batch.action_import()
        self.assertEqual(self.env['account.move'].search_count([]) - moves_before, 3)
        self.assertEqual(self.env['account.move'].search_count([('state', '=', 'posted'), ('is_legacy', '=', True)]), 0)
        f = self._file(8001)
        self.assertEqual(f.invoice_count, 2)
        self.assertEqual(f.legacy_invoice_count, 2)
        self.assertFalse(f.invoice_id, "An imported draft is never the workflow's current invoice.")
        inv = f.invoice_ids.filtered(lambda m: m.name == "EL26IM228")
        self.assertEqual(inv.state, 'draft')
        self.assertTrue(inv.is_legacy)
        self.assertEqual(inv.move_type, 'out_invoice')
        self.assertEqual(inv.partner_id.legacy_id, 2)
        self.assertEqual(str(inv.invoice_date), "2026-03-26")
        self.assertEqual(inv.legacy_amount_untaxed, 52000)
        self.assertEqual(inv.legacy_amount_total, 312010)
        self.assertEqual(inv.legacy_amount_residual, 312010)
        self.assertEqual(inv.legacy_payment_state, 'not_paid')
        self.assertEqual(inv.amount_total, 312010,
                         "The draft totals exactly what Teese invoiced (lines + a Teese VAT line).")
        vat = inv.invoice_line_ids.filtered(lambda l: l.name.startswith("TVA"))
        self.assertEqual(vat.price_unit, 10010)
        deb = inv.invoice_line_ids.filtered(lambda l: "[Débours]" in l.name)
        self.assertEqual(deb.price_unit, 250000)
        self.assertEqual(deb.account_id, self.oop)
        self.assertFalse(deb.tax_ids)
        with self.assertRaises(UserError):
            inv.action_post()
        self.assertEqual(inv.state, 'draft', "Still a draft after the refused post.")
        credit = f.invoice_ids.filtered(lambda m: m.name == "AV26IM001")
        self.assertEqual(credit.move_type, 'out_refund')
        self.assertEqual(credit.amount_total, 10000, "Refund lines are positive in Odoo.")
        self.assertEqual(credit.legacy_amount_total, -10000, "Teese figure kept as exported.")
        self.assertEqual(f.legacy_billed_total, 302010)
        self.assertEqual(f.legacy_outstanding_total, 312010)
        self.assertEqual(f.legacy_expense_total, 250000,
                         "Disbursements and revenue readable together: 50000 + 200000, reversal excluded.")
        orphan = self.env['account.move'].search([('name', '=', "EL26ND045"), ('is_legacy', '=', True)])
        self.assertTrue(orphan, "An invoice with no dossier is still kept.")
        self.assertFalse(orphan.logistics_file_id)
        self.assertEqual(orphan.legacy_payment_state, 'partial')

    def test_05b_a_real_invoice_can_still_be_raised_on_a_legacy_file(self):
        """The imported drafts must not block billing new work on a file
        that is still open."""
        self.batch.action_import()
        f = self._file(8001)
        self.assertFalse(f.invoice_id)
        # nothing billable yet -> the guard that fires must be the state or
        # the accounts, not "already has invoice"
        f.customs_fee_amount = 1000
        f.state = 'ops_closed'
        f.action_create_invoice()
        self.assertTrue(f.invoice_id)
        self.assertFalse(f.invoice_id.is_legacy)
        self.assertEqual(f.invoice_count, 3)

    def test_06_sequence_jumps_past_the_imported_numbers(self):
        self.batch.action_import()
        im = self.env['logistics.service.type'].search([('code', '=', 'IM')], limit=1)
        new = self.env['logistics.file'].create({
            'partner_id': self.env.company.partner_id.id, 'service_type_id': im.id,
            'date_opened': "2026-06-01"})
        self.assertEqual(new.name, "2026IM0008", "Must not reuse a legacy number.")

    def test_07_rerun_is_idempotent(self):
        self.batch.action_import()
        again = self.env['logistics.legacy.import'].create({
            'name': "again", 'zip_file': self.batch.zip_file, 'zip_filename': "fixture.zip"})
        again.action_import()
        self.assertEqual(again.state, 'done', again.log)
        self.assertEqual(again.count_files, 0)
        self.assertEqual(again.count_expenses, 0)
        self.assertEqual(again.count_invoices, 0)
        self.assertEqual(again.count_partners, 0)
        self.assertEqual(self.env['logistics.file'].search_count([('legacy_id', '!=', 0)]), 4)
        self.assertEqual(self.env['account.move'].search_count([('is_legacy', '=', True)]), 3)

    def test_08_validations_are_archived_not_imported(self):
        self.batch.action_import()
        att = self.env['ir.attachment'].search([
            ('res_model', '=', 'logistics.legacy.import'), ('res_id', '=', self.batch.id)])
        self.assertIn("wh_fact_validation.csv", att.mapped('name'))

    def test_09_rows_after_the_cutoff_are_counted_and_flagged(self):
        batch = self.env['logistics.legacy.import'].create({
            'name': "late", 'zip_file': base64.b64encode(build_zip(after_cutoff=True)),
            'zip_filename': "late.zip", 'cutoff_date': "2026-08-31"})
        batch.action_import()
        self.assertEqual(batch.state, 'done', batch.log)
        self.assertEqual(batch.count_after_cutoff, 1)
        self.assertIn("dated after the cutoff", batch.log)
        late = self.env['account.move'].search([('name', '=', "EL26IM900"), ('is_legacy', '=', True)])
        self.assertTrue(late, "Still imported for the record.")
