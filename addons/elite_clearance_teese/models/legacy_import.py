import base64
import csv
import io
import logging
import re
import traceback
import zipfile
from collections import defaultdict
from datetime import datetime

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TABLES = {
    'partner': 'wh_dim_partner.csv',
    'dossier': 'wh_fact_dossier.csv',
    'invoice': 'wh_fact_invoice.csv',
    'line': 'wh_fact_invoice_line.csv',
    'advance': 'wh_fact_advance.csv',
    'validation': 'wh_fact_validation.csv',
}
SYNC_STATE = '_sync_state.csv'

# Teese dossier type -> Clearance service type. The legacy code prefix (IM,
# AI, EX, ET, TP...) is NOT used for this: the export shows the same prefix
# under several types, so the label is the only reliable signal. The raw
# label is kept on the file (legacy_type_name) because this is a judgement.
TYPE_MAP = {
    'MISE A LA CONSOMMATION': ('IM', "Import"),
    'EXPORT STANDARD': ('ES', "Export Standard"),
    'ENLEVEMENT DIRECT ET APUREMENT': ('ED', "Enlèvement direct et apurement"),
    'AUTRE': ('AU', "Autre (legacy)"),
}
DEFAULT_TYPE = ('AU', "Autre (legacy)")

SHIPMENT_MAP = {
    'CONTENEUR': 'container',
    'CONVENTIONNEL': 'conventional',
    'CAMION PLATEAU': 'flatbed',
}

# The four products the legacy invoices were billed under, named from their
# line labels. Kept as labels on the imported lines; no product is created.
# product_odoo_id -> (code, name, is_debours)
PRODUCTS = {
    '1447': ('LEG-1447', "Débours", True),
    '1449': ('LEG-1449', "Honoraires", False),
    '5538': ('LEG-5538', "Débours douane — vacation / liquidation", True),
    '5541': ('LEG-5541', "Droits de douane", True),
}

LEGACY_CATEGORY = ('LEG', "Legacy — non catégorisé")
UNALLOCATED_FILE = "LEGACY-UNALLOCATED"
UNALLOCATED_LEGACY_ID = -1
REF_RE = re.compile(r'^(\d{4})([A-Z]{2})(\d{4})$')
CHUNK = 500
PAYMENT_STATES = {'not_paid', 'partial', 'paid'}


def _f(value):
    try:
        return float(value) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _d(value):
    """'2026-03-30' or '2026-08-26 21:24:07' -> date, else None."""
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


class LogisticsLegacyImport(models.Model):
    """One run of the Teese warehouse import.

    Record-keeping only. Nothing this import creates touches the ledger:
    legacy expenses carry no journal entry and legacy invoices are not
    account.move records. The books close at the cutoff date and their
    balances arrive as an uploaded trial balance.

    Persistent, not a wizard, so every run keeps its zip, its counts and its
    log, and the validation history it archives has somewhere to live.
    """

    _name = 'logistics.legacy.import'
    _description = "Teese Legacy Import"
    _order = 'id desc'

    name = fields.Char(required=True, default=lambda self: self.env._(
        "Teese import %s", fields.Date.context_today(self).strftime("%d/%m/%Y")))
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    zip_file = fields.Binary(string="Export (zip)", attachment=True, required=True)
    zip_filename = fields.Char()
    cutoff_date = fields.Date(
        string="Cutoff Date", required=True, default="2026-08-31",
        help="The legacy books close on this date and their balances are "
             "uploaded as a trial balance. Rows dated after it are still "
             "imported for the record, but counted and logged: they are "
             "not in that trial balance.")
    export_synced_at = fields.Datetime(
        string="Export Synced At", readonly=True,
        help="When the warehouse last synchronised from Teese, read from "
             "_sync_state.csv. If earlier than the cutoff, the export does "
             "not cover the whole period.")
    state = fields.Selection(
        [('draft', "Draft"), ('done', "Done"), ('error', "Error")],
        default='draft', required=True)
    date_done = fields.Datetime(readonly=True)
    log = fields.Text(readonly=True)

    count_partners = fields.Integer(readonly=True)
    count_suppliers = fields.Integer(readonly=True)
    count_employees = fields.Integer(readonly=True)
    count_ports = fields.Integer(readonly=True)
    count_files = fields.Integer(readonly=True)
    count_expenses = fields.Integer(readonly=True)
    count_invoices = fields.Integer(readonly=True)
    count_lines = fields.Integer(readonly=True)
    count_after_cutoff = fields.Integer(
        string="Rows dated after cutoff", readonly=True)

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------
    def action_import(self):
        self.ensure_one()
        if not self.zip_file:
            raise UserError(self.env._("Upload the Teese export zip first."))
        tables = self._read_zip()
        self._run(tables)
        return True

    def _read_zip(self):
        raw = base64.b64decode(self.zip_file)
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            raise UserError(self.env._("That file is not a zip archive."))
        names = set(archive.namelist())
        missing = [f for f in TABLES.values() if f not in names]
        if missing:
            raise UserError(self.env._(
                "The archive is missing: %s", ", ".join(missing)))
        tables = {}
        for key, filename in TABLES.items():
            text = archive.read(filename).decode('utf-8-sig')
            tables[key] = list(csv.DictReader(io.StringIO(text)))
        tables['validation_raw'] = archive.read(TABLES['validation'])
        tables['synced_at'] = None
        if SYNC_STATE in names:
            rows = list(csv.DictReader(io.StringIO(archive.read(SYNC_STATE).decode('utf-8-sig'))))
            stamps = [_dt(r.get('last_run_at', '')) for r in rows]
            stamps = [s for s in stamps if s]
            tables['synced_at'] = max(stamps) if stamps else None
        return tables

    # ------------------------------------------------------------------
    # the run: one savepoint per phase, so a failure keeps what worked
    # ------------------------------------------------------------------
    def _run(self, tables):
        # sudo(): a migration is not a person keying records. The gates that
        # bind users (who may key an expense, who may set its settlement)
        # are exempt under su by design.
        E = self.sudo().with_context(
            legacy_import=True, skip_checklist=True,
            tracking_disable=True, mail_create_nolog=True,
            mail_create_nosubscribe=True, mail_notrack=True,
        ).env
        lines = []
        counts = {'after_cutoff': 0}

        def log(msg):
            lines.append(msg)
            _logger.info("legacy import %s: %s", self.id, msg)

        synced = tables.get('synced_at')
        if synced:
            self.export_synced_at = synced
            log("export synchronised from Teese at %s; cutoff %s" % (synced, self.cutoff_date))
            if synced.date() < self.cutoff_date:
                log("WARNING: the export predates the cutoff by %d day(s). "
                    "Anything Teese recorded between %s and %s is NOT in this "
                    "import." % ((self.cutoff_date - synced.date()).days,
                                 synced.date(), self.cutoff_date))
        else:
            log("no _sync_state.csv in the archive: export date unknown")

        phases = [
            ("ports", self._import_ports),
            ("employees", self._import_employees),
            ("service types", self._import_service_types),
            ("partners", self._import_partners),
            ("files", self._import_files),
            ("expenses", self._import_expenses),
            ("invoices", self._import_invoices),
            ("validations archive", self._archive_validations),
        ]
        ctx = {'log': log, 'counts': counts, 'company': self.company_id,
               'maps': {}, 'cutoff': self.cutoff_date}
        label = None
        try:
            for label, phase in phases:
                with self.env.cr.savepoint():
                    log("--- %s" % label)
                    phase(E, tables, ctx)
        except Exception:
            log("FAILED in phase '%s':\n%s" % (label, traceback.format_exc()))
            self.write({'state': 'error', 'log': "\n".join(lines),
                        **{'count_%s' % k: v for k, v in counts.items()}})
            return
        if counts['after_cutoff']:
            log("WARNING: %d row(s) dated after the cutoff were imported for the "
                "record; they are not in the trial balance." % counts['after_cutoff'])
        self.write({
            'state': 'done',
            'date_done': fields.Datetime.now(),
            'log': "\n".join(lines),
            **{'count_%s' % k: v for k, v in counts.items()},
        })

    def _after_cutoff(self, ctx, day):
        if day and ctx['cutoff'] and day > ctx['cutoff']:
            ctx['counts']['after_cutoff'] += 1

    # ------------------------------------------------------------------
    # dimensions
    # ------------------------------------------------------------------
    def _import_ports(self, E, tables, ctx):
        Port = E['logistics.port']
        by_name = {p.name.upper(): p for p in Port.with_context(active_test=False).search([])}
        created = 0
        for name in sorted({r['port_name'].strip().upper() for r in tables['dossier'] if r['port_name'].strip()}):
            if name not in by_name:
                by_name[name] = Port.create({'name': name.title()})
                created += 1
        ctx['maps']['port'] = by_name
        ctx['counts']['ports'] = created
        ctx['log']("%d ports, %d created" % (len(by_name), created))

    def _import_employees(self, E, tables, ctx):
        Emp = E['hr.employee']
        by_name = {}
        for emp in Emp.with_context(active_test=False).search([('company_id', '=', ctx['company'].id)]):
            by_name.setdefault(emp.name.strip().upper(), emp)
        created = 0
        for name in sorted({r['employee_name'].strip() for r in tables['dossier'] if r['employee_name'].strip()}):
            key = name.upper()
            if key not in by_name:
                by_name[key] = Emp.create({'name': name, 'company_id': ctx['company'].id})
                created += 1
        ctx['maps']['employee'] = by_name
        ctx['counts']['employees'] = created
        ctx['log']("%d employees, %d created" % (len(by_name), created))

    def _import_service_types(self, E, tables, ctx):
        Service = E['logistics.service.type']
        company = ctx['company']
        by_label = {}
        created = 0
        labels = {r['type_name'].strip().upper() for r in tables['dossier']}
        for label in sorted(labels):
            code, name = TYPE_MAP.get(label, DEFAULT_TYPE)
            st = Service.search([('code', '=', code), ('company_id', 'in', [company.id, False])], limit=1)
            if not st:
                st = Service.create({'code': code, 'name': name, 'company_id': company.id,
                                     'commission_rate': 2.0, 'sequence': 90})
                created += 1
                ctx['log']("created service type %s (%s) for legacy type %r" % (code, name, label))
            elif label not in TYPE_MAP:
                ctx['log']("legacy type %r not in TYPE_MAP - mapped to %s" % (label, code))
            by_label[label] = st
        ctx['maps']['service_type'] = by_label
        ctx['log']("%d service types, %d created" % (len(by_label), created))

    def _import_partners(self, E, tables, ctx):
        Partner = E['res.partner']
        existing = {p.legacy_id: p for p in Partner.with_context(active_test=False).search([('legacy_id', '!=', 0)])}
        by_legacy = {}
        vals_list = []
        for r in tables['partner']:
            lid = int(r['odoo_id'])
            if lid in existing:
                by_legacy[lid] = existing[lid]
                continue
            vals_list.append({
                'name': r['name'].strip(),
                'ref': r['ref'].strip() or False,
                'is_company': r['is_company'] == '1',
                'customer_rank': 1,
                'legacy_id': lid,
                'company_id': False,
            })
        created = Partner.create(vals_list) if vals_list else Partner
        for p in created:
            by_legacy[p.legacy_id] = p
        ctx['maps']['partner'] = by_legacy
        ctx['counts']['partners'] = len(created)
        ctx['log']("%d partners in export, %d created, %d already present"
                   % (len(tables['partner']), len(created), len(existing)))

    def _supplier(self, E, ctx, name):
        """Suppliers arrive as free-text names on the advance lines."""
        cache = ctx['maps'].setdefault('supplier', {})
        key = name.strip().upper()
        if key in cache:
            return cache[key]
        Partner = E['res.partner']
        partner = Partner.search([('name', '=ilike', name.strip())], limit=1)
        if not partner:
            partner = Partner.create({'name': name.strip(), 'is_company': True,
                                      'supplier_rank': 1, 'company_id': False})
            ctx['counts']['suppliers'] = ctx['counts'].get('suppliers', 0) + 1
        elif not partner.supplier_rank:
            partner.supplier_rank = 1
        cache[key] = partner
        return partner

    # ------------------------------------------------------------------
    # files
    # ------------------------------------------------------------------
    def _import_files(self, E, tables, ctx):
        File = E['logistics.file']
        company = ctx['company']
        maps = ctx['maps']
        log = ctx['log']
        existing = {f.legacy_id: f for f in File.search([('legacy_id', '!=', 0), ('company_id', '=', company.id)])}
        taken = set(File.search([('company_id', '=', company.id)]).mapped('name'))
        by_legacy = dict(existing)
        incoterms = {i.code: i for i in E['account.incoterms'].search([]) if i.code}
        vals_list, skipped, renamed, undated = [], 0, 0, 0
        max_ref = defaultdict(int)   # (year, code) -> highest number seen

        for r in tables['dossier']:
            lid = int(r['odoo_id'])
            code = r['code'].strip()
            m = REF_RE.match(code)
            if m:
                max_ref[(m.group(1), m.group(2))] = max(max_ref[(m.group(1), m.group(2))], int(m.group(3)))
            if lid in existing:
                skipped += 1
                continue
            name = code
            if name in taken:
                name = "%s-%s" % (code, lid)
                renamed += 1
                log("duplicate code %s: legacy %s imported as %s" % (code, lid, name))
            taken.add(name)
            opened = _d(r['opened_date'])
            if not opened:
                undated += 1
                opened = _d("%s-01-01" % code[:4]) if code[:4].isdigit() else _d(r['write_date'])
                log("legacy %s (%s) has no opening date - using %s" % (lid, code, opened))
            self._after_cutoff(ctx, opened)
            partner = maps['partner'].get(int(r['partner_odoo_id']) if r['partner_odoo_id'] else 0)
            if not partner:
                partner = company.partner_id
                log("legacy %s (%s): client %r not in partner export - attached to the company" % (lid, code, r['client_name']))
            service = maps['service_type'].get(r['type_name'].strip().upper())
            closed = r['is_closed'] == '1'
            vals_list.append({
                'name': name,
                'partner_id': partner.id,
                'service_type_id': service.id,
                'company_id': company.id,
                'state': 'done' if closed else 'in_progress',
                'date_opened': opened,
                'date_closed': _d(r['closed_date']) if closed else False,
                'port_id': maps['port'].get(r['port_name'].strip().upper()).id if r['port_name'].strip() else False,
                'employee_id': maps['employee'].get(r['employee_name'].strip().upper()).id if r['employee_name'].strip() else False,
                'shipment_type': SHIPMENT_MAP.get(r['embarquement'].strip().upper(), False),
                'container_count': int(_f(r['containers'])),
                'package_count': int(_f(r['packages'])),
                'weight_kg': _f(r['weight_kg']),
                'cargo_value': _f(r['cargo_value']),
                'customs_regime': r['regime'].strip() or False,
                'incoterm_id': incoterms.get(r['incoterm'].strip().upper(), E['account.incoterms']).id or False,
                'importer_name': r['importer'].strip() or False,
                'legacy_id': lid,
                'legacy_type_name': r['type_name'].strip(),
                'customs_fee_amount': 0.0,
            })

        created_total = 0
        for i in range(0, len(vals_list), CHUNK):
            created = File.create(vals_list[i:i + CHUNK])
            created_total += len(created)
            for f in created:
                by_legacy[f.legacy_id] = f

        # the parking file for advances the legacy system never attached
        park = File.search([('legacy_id', '=', UNALLOCATED_LEGACY_ID), ('company_id', '=', company.id)], limit=1)
        if not park:
            park = File.create({
                'name': UNALLOCATED_FILE,
                'partner_id': company.partner_id.id,
                'service_type_id': maps['service_type'].get('AUTRE', next(iter(maps['service_type'].values()))).id,
                'company_id': company.id,
                'state': 'in_progress',
                'date_opened': fields.Date.context_today(self),
                'legacy_id': UNALLOCATED_LEGACY_ID,
                'legacy_type_name': "Advances with no dossier in Teese",
                'note': "<p>Parking file created by the Teese import for advances the legacy system never attached to a dossier. Reallocate them from here.</p>",
            })
        by_legacy[UNALLOCATED_LEGACY_ID] = park

        self._advance_sequences(E, ctx, max_ref)
        maps['file'] = by_legacy
        ctx['counts']['files'] = created_total
        log("%d dossiers in export, %d created, %d already present, %d renamed for duplicate code, %d without opening date"
            % (len(tables['dossier']), created_total, skipped, renamed, undated))

    def _advance_sequences(self, E, ctx, max_ref):
        """New files must not reuse a number the legacy system already used.

        Only the (year, code) pairs whose two-letter code is one of OUR
        service type codes can collide: the sequence for that code and year
        is pushed past the highest imported number.
        """
        company = ctx['company']
        services = {s.code.upper(): s for s in E['logistics.service.type'].search(
            [('company_id', 'in', [company.id, False])]) if s.code}
        File = E['logistics.file']
        for (year, code), highest in sorted(max_ref.items()):
            service = services.get(code)
            if not service or not year.isdigit():
                continue
            seq = File._get_reference_sequence('file', service, company)
            date_from, date_to = "%s-01-01" % year, "%s-12-31" % year
            rng = seq.date_range_ids.filtered(
                lambda d: str(d.date_from) == date_from and str(d.date_to) == date_to)
            if not rng:
                # Create, THEN write. ir.sequence.date_range.create() seeds the
                # PostgreSQL sequence from number_next_actual (forced to 1 by
                # default_get) and ignores a number_next passed at creation;
                # only write() issues ALTER SEQUENCE ... RESTART WITH.
                rng = E['ir.sequence.date_range'].create({
                    'sequence_id': seq.id, 'date_from': date_from, 'date_to': date_to})
                rng.write({'number_next': highest + 1})
                ctx['log']("sequence %s/%s starts at %d" % (code, year, highest + 1))
            elif rng.number_next <= highest:
                rng.number_next = highest + 1
                ctx['log']("sequence %s/%s advanced to %d" % (code, year, highest + 1))

    # ------------------------------------------------------------------
    # expenses (avances de frais)
    # ------------------------------------------------------------------
    def _import_expenses(self, E, tables, ctx):
        Expense = E['logistics.expense']
        company = ctx['company']
        maps = ctx['maps']
        log = ctx['log']
        Cat = E['logistics.expense.category']
        cat = Cat.search([('code', '=', LEGACY_CATEGORY[0]), ('company_id', 'in', [company.id, False])], limit=1)
        if not cat:
            cat = Cat.create({'code': LEGACY_CATEGORY[0], 'name': LEGACY_CATEGORY[1],
                              'company_id': company.id, 'sequence': 990})
        existing = set(Expense.search([('legacy_id', '!=', 0), ('company_id', '=', company.id)]).mapped('legacy_id'))
        vals_list, skipped, parked, reversals, justified = [], 0, 0, 0, 0
        for r in tables['advance']:
            lid = int(r['odoo_id'])
            if lid in existing:
                skipped += 1
                continue
            file = maps['file'].get(int(r['dossier_odoo_id'])) if r['dossier_odoo_id'] else None
            if not file:
                file = maps['file'][UNALLOCATED_LEGACY_ID]
                parked += 1
            amount = _f(r['amount'])
            reversal = amount <= 0
            reversals += reversal
            is_just = r['is_justified'] == '1'
            justified += is_just
            disbursed = _d(r['disbursed_date'])
            self._after_cutoff(ctx, disbursed)
            vals_list.append({
                'name': "LEG/%d" % lid,
                'file_id': file.id,
                'category_id': cat.id,
                'description': (r['label'].strip() or "Avance de frais")[:250],
                'amount': abs(amount),
                # Payment mode and holder were not exported; the money left
                # in the legacy system and was billed there. Settled-direct
                # is the neutral reading, and is_legacy keeps it out of every
                # total that matters. No journal entry is ever created.
                'payment_mode': 'direct',
                'state': 'cancel' if reversal else 'settled',
                'vendor_id': self._supplier(E, ctx, r['supplier_name']).id if r['supplier_name'].strip() else False,
                'date_requested': _d(r['requested_date']),
                'date_settled': datetime.combine(disbursed, datetime.min.time()) if disbursed else False,
                'is_legacy': True,
                'legacy_id': lid,
                'legacy_justified': is_just,
                'legacy_reversal': reversal,
            })
        created_total = 0
        for i in range(0, len(vals_list), CHUNK):
            created_total += len(Expense.create(vals_list[i:i + CHUNK]))
        ctx['counts']['expenses'] = created_total
        ctx['counts'].setdefault('suppliers', 0)
        log("%d advances in export, %d created, %d already present, %d parked on %s, %d reversals/zero kept cancelled, %d flagged justified in Teese"
            % (len(tables['advance']), created_total, skipped, parked, UNALLOCATED_FILE, reversals, justified))

    # ------------------------------------------------------------------
    # invoices: draft customer invoices that can never be posted
    # ------------------------------------------------------------------
    def _import_invoices(self, E, tables, ctx):
        """Each legacy invoice becomes a DRAFT account.move flagged is_legacy,
        so it shows in Invoicing and on its file under the billing reference
        the client knows. account.move.action_post refuses is_legacy: the
        revenue is in the trial balance uploaded at the cutoff.

        The draft is built to total exactly what Teese invoiced: the lines as
        exported, tax-free, plus one "TVA (as invoiced in Teese)" line for
        the difference between the Teese total and the sum of its lines.
        Nothing here is accounting; it is the invoice as the client saw it.
        """
        Move = E['account.move']
        company = ctx['company']
        maps = ctx['maps']
        log = ctx['log']
        journal = company.clearance_sale_journal_id or E['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not journal:
            raise UserError(self.env._("Company %s has no sales journal.", company.name))
        oop_account = company.clearance_oop_account_id
        fee_account = company.clearance_fee_account_id
        lines_by_move = defaultdict(list)
        for r in tables['line']:
            lines_by_move[r['move_odoo_id']].append(r)
        existing = set(Move.search([('is_legacy', '=', True), ('company_id', '=', company.id)]).mapped('legacy_id'))
        vals_list, skipped, refunds, unlinked, nlines = [], 0, 0, 0, 0
        for r in tables['invoice']:
            lid = int(r['odoo_id'])
            if lid in existing:
                skipped += 1
                continue
            total = _f(r['amount_total'])
            is_refund = total < 0
            refunds += is_refund
            sign = -1.0 if is_refund else 1.0
            file = maps['file'].get(int(r['dossier_odoo_id'])) if r['dossier_odoo_id'] else None
            if not file:
                unlinked += 1
            partner = maps['partner'].get(int(r['partner_odoo_id']) if r['partner_odoo_id'] else 0)
            if not partner:
                log("invoice %s: partner %s not in export - attached to the company" % (r['name'], r['partner_odoo_id']))
                partner = company.partner_id
            inv_date = _d(r['invoice_date'])
            self._after_cutoff(ctx, inv_date)
            analytic = {str(file.analytic_account_id.id): 100} if file and file.analytic_account_id else False
            line_cmds, lines_sum = [], 0.0
            for lr in lines_by_move.get(r['odoo_id'], []):
                code, label, is_debours = PRODUCTS.get(
                    lr['product_odoo_id'],
                    ("LEG-%s" % lr['product_odoo_id'], "Legacy product %s" % lr['product_odoo_id'], lr['is_debours'] == '1'))
                is_debours = is_debours or lr['is_debours'] == '1'
                qty = _f(lr['quantity']) or 1.0
                unit = _f(lr['price_unit'])
                lines_sum += _f(lr['price_subtotal'])
                lv = {
                    'name': "%s [%s]" % ((lr['label'].strip() or label)[:480], label),
                    'quantity': qty,
                    'price_unit': sign * unit,
                    'tax_ids': [fields.Command.clear()],
                    'analytic_distribution': analytic,
                }
                if is_debours and oop_account:
                    lv['account_id'] = oop_account.id
                elif not is_debours and fee_account:
                    lv['account_id'] = fee_account.id
                line_cmds.append(fields.Command.create(lv))
                nlines += 1
            vat = total - lines_sum
            if abs(vat) >= 0.5:
                lv = {'name': "TVA (as invoiced in Teese)", 'quantity': 1.0,
                      'price_unit': sign * vat, 'tax_ids': [fields.Command.clear()]}
                if fee_account:
                    lv['account_id'] = fee_account.id
                line_cmds.append(fields.Command.create(lv))
            payment_state = r['payment_state'].strip()
            vals_list.append({
                'move_type': 'out_refund' if is_refund else 'out_invoice',
                'journal_id': journal.id,
                'company_id': company.id,
                'name': r['name'].strip(),
                'partner_id': partner.id,
                'invoice_date': inv_date,
                'invoice_date_due': _d(r['invoice_date_due']) or inv_date,
                'invoice_origin': file.name if file else False,
                'ref': file.name if file else False,
                'logistics_file_id': file.id if file else False,
                'is_legacy': True,
                'legacy_id': lid,
                'legacy_amount_untaxed': _f(r['amount_untaxed']),
                'legacy_amount_total': total,
                'legacy_amount_residual': _f(r['amount_residual']),
                'legacy_payment_state': payment_state if payment_state in PAYMENT_STATES else 'not_paid',
                'invoice_line_ids': line_cmds,
            })
        created_total = 0
        for i in range(0, len(vals_list), CHUNK):
            created_total += len(Move.create(vals_list[i:i + CHUNK]))
        ctx['counts']['invoices'] = created_total
        ctx['counts']['lines'] = nlines
        log("%d invoices in export, %d created as DRAFT customer invoices (%d credit notes), %d already present, %d not tied to a file, %d lines - none posted, none postable"
            % (len(tables['invoice']), created_total, refunds, skipped, unlinked, nlines))

    # ------------------------------------------------------------------
    # validations: history, not data
    # ------------------------------------------------------------------
    def _archive_validations(self, E, tables, ctx):
        Att = E['ir.attachment']
        name = TABLES['validation']
        if not Att.search([('res_model', '=', self._name), ('res_id', '=', self.id), ('name', '=', name)], limit=1):
            Att.create({'name': name, 'res_model': self._name, 'res_id': self.id,
                        'raw': tables['validation_raw'], 'mimetype': 'text/csv'})
        ctx['log']("%d validation steps archived as %s on this record (approval history; the circuits are rebuilt as Odoo approvals, not imported)"
                   % (len(tables['validation']), name))
