from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestReportViewerTour(HttpCase):
    """The report viewer in a real browser.

    Drives static/tests/tours/report_viewer_tour.js as the administrator:
    the general ledger is on screen the moment the menu is clicked, the
    quick bar re-renders it, and "More filters" opens the wizard's form
    with Apply in place of View / Export. Needs Chrome on the machine
    running the suite; CI installs it.
    """

    def test_01_the_general_ledger_opens_at_once(self):
        self.env.company.external_report_layout_id = self.env.ref('web.external_layout_standard')
        self.start_tour(
            "/odoo/action-elite_finance.action_view_general_ledger",
            "elite_finance_report_viewer", login="admin")
