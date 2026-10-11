import { registry } from "@web/core/registry";

/**
 * A report opens at once and its filters sit on the page (owner,
 * 11/10/2026). Driven in a real browser by tests/test_report_viewer_tour.py:
 * the general ledger shows without a dialog, the quick bar re-renders it
 * on Apply, and "More filters" opens the wizard's form with Apply in its
 * footer and no View / Export buttons.
 */
registry.category("web_tour.tours").add("elite_finance_report_viewer", {
    steps: () => [
        {
            content: "The report is on screen at once, no dialog first",
            trigger: ".o_elite_report_viewer iframe.o_elite_report_frame",
        },
        {
            content: "The quick bar offers the entries filter",
            trigger: ".o_elite_report_bar select[name='target_move']",
            run: "selectByLabel All Entries",
        },
        {
            content: "Apply re-renders the report",
            trigger: ".o_elite_report_bar button.o_elite_report_apply",
            run: "click",
        },
        {
            content: "Still a report on screen",
            trigger: ".o_elite_report_viewer iframe.o_elite_report_frame",
        },
        {
            content: "More filters opens the wizard's own form",
            trigger: ".o_elite_report_bar button.o_elite_report_more",
            run: "click",
        },
        {
            content: "with Apply in its footer and no View / Export buttons",
            trigger: ".modal footer:has(button:contains('Apply')):not(:has(button[name='button_export_html']:visible)):not(:has(button[name='button_export_pdf']:visible))",
        },
        {
            trigger: ".modal footer button:contains('Apply')",
            run: "click",
        },
        {
            content: "The dialog is gone and the report is back",
            trigger: "body:not(:has(.modal)) .o_elite_report_viewer iframe.o_elite_report_frame",
        },
    ],
});
