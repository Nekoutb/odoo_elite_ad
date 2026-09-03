import itertools
import re
import string
import unicodedata

from odoo import fields, models

# Words that say nothing about who a client is, so they never earn a letter
# in the slug. French and English, because Elimelec's ledger holds both.
SLUG_NOISE = {
    'SARL', 'SARLU', 'SA', 'SAS', 'SASU', 'SPRL', 'SNC', 'SCI', 'GIE',
    'LTD', 'LTDA', 'LIMITED', 'LLC', 'PLC', 'INC', 'CORP', 'CO',
    'ETS', 'ETABLISSEMENT', 'ETABLISSEMENTS', 'CIE', 'COMPAGNIE', 'COMPANY',
    'GROUP', 'GROUPE', 'SOCIETE', 'ENTREPRISE', 'ENTREPRISES',
    'DU', 'DE', 'DES', 'DA', 'LA', 'LE', 'LES', 'L', 'D', 'ET', 'AND',
    'THE', 'OF', 'EN', 'AU', 'AUX',
}
# Third-character alphabet used to break a tie: digits first so a collision
# reads as one (CTC, CTC2), then letters.
SLUG_TIEBREAK = string.digits[2:] + string.ascii_uppercase


class ResPartner(models.Model):
    _inherit = 'res.partner'

    legacy_id = fields.Integer(
        string="Legacy ID", index=True, copy=False,
        help="Identifier of this partner in the legacy Teese system. Set "
             "only by the migration; makes re-imports idempotent.")
    clearance_slug = fields.Char(
        string="Clearance Slug", size=3, index=True, copy=False, tracking=True,
        help="Three letters standing for this client in clearance analytic "
             "accounts, so every file reads the same width: 2026AI0072 - CTC. "
             "Generated when the client's first file is opened and kept for "
             "good — changing it rewrites nothing already posted.")

    _clearance_slug_uniq = models.Constraint(
        'UNIQUE(clearance_slug)',
        "Another contact already uses this clearance slug. Three letters "
        "have to point at one client to be worth anything.")

    def _clearance_slug_candidate(self):
        """Three letters derived from the name, before any tie-breaking.

        Initials when the name has three telling words or more
        (SOCIETE DES BOISSONS DU CAMEROUN -> SBC), otherwise the opening
        letters (PIZZAROTI -> PIZ, CTC -> CTC).
        """
        self.ensure_one()
        folded = unicodedata.normalize('NFKD', self.name or '')
        folded = ''.join(c for c in folded if not unicodedata.combining(c))
        folded = re.sub(r'[^A-Za-z ]+', ' ', folded).upper()
        words = folded.split()
        telling = [w for w in words if w not in SLUG_NOISE] or words
        if len(telling) >= 3:
            base = ''.join(word[0] for word in telling[:3])
        else:
            base = ''.join(telling)[:3]
        return (base + 'XXX')[:3]

    def _clearance_ensure_slug(self):
        """The slug for this partner, generated once and then left alone.

        It lives on the commercial partner, because that is the entity the
        analytic account names and the one Odoo itself shows on an analytic
        account.
        """
        self.ensure_one()
        owner = self.commercial_partner_id or self
        if owner.clearance_slug:
            return owner.clearance_slug
        taken = set(self.sudo().with_context(active_test=False).search(
            [('clearance_slug', '!=', False)]).mapped('clearance_slug'))
        base = owner._clearance_slug_candidate()
        options = itertools.chain(
            [base],
            (base[:2] + c for c in SLUG_TIEBREAK),
            (base[:1] + a + b for a in SLUG_TIEBREAK for b in SLUG_TIEBREAK),
        )
        slug = next(c for c in options if c not in taken)
        # sudo(): the slug is an identifier the system assigns, not
        # something the ops agent opening a file is choosing to write.
        owner.sudo().clearance_slug = slug
        return slug
