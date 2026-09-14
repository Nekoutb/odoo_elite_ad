import { registry } from "@web/core/registry";

/**
 * The bell at the top right, driven the way an Operations Manager drives
 * it: see that something is waiting, open the list, click the task, land
 * on the record itself. Run by tests/test_task_systray_tour.py in a real
 * Chromium, because a systray component that throws takes the whole top
 * of everybody's screen with it and no ORM test would ever see that.
 *
 * The count is asserted as "there is one" rather than as a number: an
 * Operations Manager holds more than one kind of queue, and a tour that
 * counts them would break the day a kind is added.
 */
registry.category("web_tour.tours").add("elite_clearance_task_systray", {
    steps: () => [
        {
            content: "The bell says something is waiting",
            trigger: ".o_clearance_tasks .o_clearance_tasks_count",
        },
        {
            content: "Open the list of what is waiting",
            trigger: ".o_clearance_tasks button",
            run: "click",
        },
        {
            content: "The disbursement waiting for approval is listed",
            trigger:
                ".o_clearance_tasks_menu .o_clearance_task_row:contains('Approve expense')",
            run: "click",
        },
        {
            content: "Clicking it opened the expense itself, not a list",
            trigger: ".o_form_view .o_statusbar_status:contains('Submitted')",
        },
    ],
});
