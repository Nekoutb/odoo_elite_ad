"""Bare figures on the accounting reports (owner, 11/10/2026).

The OCA templates render every amount through the monetary widget,
which appends the currency symbol - "45,000 FCFA" in every cell of a
report whose title already says XAF - and the journal ledger through the
float widget at two decimals, on a currency that has none. Under the
context flag ``elite_finance_bare_amounts``, which the report wizards
set on their exports (models/report_wizards.py), the symbol goes and the
decimals are the currency's own. Everything else Odoo renders is
untouched: the flag travels only with those reports.
"""

import re

from markupsafe import Markup

from odoo import api, models

FLAG = 'elite_finance_bare_amounts'
VALUE_SPANS = re.compile(r'<span class="oe_currency_value"[^>]*>.*?</span>')


class IrQwebFieldMonetary(models.AbstractModel):
    _inherit = 'ir.qweb.field.monetary'

    @api.model
    def value_to_html(self, value, options):
        html = super().value_to_html(value, options)
        if not self.env.context.get(FLAG):
            return html
        spans = VALUE_SPANS.findall(html)
        return Markup(''.join(spans)) if spans else html


class IrQwebFieldFloat(models.AbstractModel):
    _inherit = 'ir.qweb.field.float'

    @api.model
    def value_to_html(self, value, options):
        if self.env.context.get(FLAG):
            decimals = self.env.company.currency_id.decimal_places
            options = dict(options, precision=decimals, min_precision=decimals)
        return super().value_to_html(value, options)
