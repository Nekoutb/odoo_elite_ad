import { registry } from "@web/core/registry";

/**
 * A report opens at once and its filters sit on the page as pills
 * (owner, 11/10/2026). Driven in a real browser by
 * tests/test_report_viewer_tour.py: the general ledger shows without a
 * dialog, the entries pill re-renders it, the period pill offers presets
 * and custom dates, the search box is there, and "More filters" opens
 * the wizard's form with Apply in its footer and no View / Export.
 */
registry.category("web_tour.tours").add("elite_finance_report_viewer", {
    steps: () => [
        {
            content: "The report is on screen at once, no dialog first",
            trigger: ".o_elite_report_viewer iframe.o_elite_report_frame",
        },
        {
            content: "The bar carries the search box and the period pill",
            trigger: ".o_elite_report_bar:has(input[name='search']):has(button.o_elite_period)",
        },
        {
            content: "The entries pill opens its menu",
            trigger: ".o_elite_report_bar button.o_elite_entries",
            run: "click",
        },
        {
            content: "All entries re-renders the report",
            trigger: ".o_elite_report_bar .o_elite_menu a:contains('All Entries')",
            run: "click",
        },
        {
            content: "The pill now reads All Entries",
            trigger: ".o_elite_report_bar button.o_elite_entries:contains('All Entries')",
        },
        {
            content: "The period pill offers presets",
            trigger: ".o_elite_report_bar button.o_elite_period",
            run: "click",
        },
        {
            content: "and custom dates",
            trigger: ".o_elite_report_bar .o_elite_menu a:contains('Custom dates')",
            run: "click",
        },
        {
            content: "with an Apply button",
            trigger: ".o_elite_report_bar .o_elite_menu button.o_elite_report_apply",
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
