import { registry } from "@web/core/registry";

/**
 * The expense capture dialog, driven the way an Operations agent drives it:
 * open it from the file, pick the category, type the amount, name the
 * vendor, drop a receipt anywhere on the dialog, press Submit. ONE press
 * (owner 19/09/2026): no saving the dialog, then the file, then finding
 * the row again to submit it. Run by tests/test_expense_dialog_tour.py in
 * a real Chromium, because a widget's drop zone and a wizard's save path
 * are things an ORM-level test never sees.
 *
 * The drag is simulated with the same DataTransfer at dragenter and at
 * drop: the page reads the file off that object, so it must be one and
 * the same.
 */
let dragged = null;

function aReceipt() {
    const transfer = new DataTransfer();
    transfer.items.add(
        new File(["Receipt for the terminal handling"], "receipt.txt", { type: "text/plain" })
    );
    return transfer;
}

// No `url` on purpose: the HttpCase opens the file's own form and a tour
// that declares one is redirected to it before its first step.
registry.category("web_tour.tours").add("elite_clearance_expense_dialog", {
    steps: () => [
        {
            content: "Add a disbursement from the file",
            trigger: "button[name='action_add_expense']",
            run: "click",
        },
        {
            content: "Pick the category",
            trigger: ".modal .o_field_widget[name='category_id'] input",
            run: "edit Tour terminal fees",
        },
        {
            trigger:
                ".modal .o_field_widget[name='category_id'] .o-autocomplete--dropdown-menu li:contains('Tour terminal fees') a",
            run: "click",
        },
        {
            content: "Describe it",
            trigger: ".modal .o_field_widget[name='description'] input",
            run: "edit Terminal handling",
        },
        {
            content: "The amount is typed in the dialog",
            trigger: ".modal .o_field_widget[name='amount'] input",
            run: "edit 25000",
        },
        {
            content: "The vendor is picked in the dialog",
            trigger: ".modal .o_field_widget[name='vendor_id'] input",
            run: "edit Douala Terminal Tour",
        },
        {
            trigger:
                ".modal .o_field_widget[name='vendor_id'] .o-autocomplete--dropdown-menu li:contains('Douala Terminal Tour') a",
            run: "click",
        },
        {
            content: "The unit is not asked for",
            trigger: ".modal .o_form_view:not(:has(.o_field_widget[name='unit_label']))",
        },
        {
            content: "Drag a receipt over the dialog",
            trigger: ".modal .o_form_view",
            run() {
                dragged = aReceipt();
                this.anchor.dispatchEvent(
                    new DragEvent("dragenter", { bubbles: true, dataTransfer: dragged })
                );
            },
        },
        {
            // The zone is mounted in the overlay container, a sibling of the
            // dialog, and the engine refuses to act outside an open modal
            // unless the trigger starts with `body`.
            content: "The drop zone covers the dialog; drop the receipt on it",
            trigger: "body .o-Dropzone",
            run() {
                this.anchor.dispatchEvent(
                    new DragEvent("drop", { bubbles: true, dataTransfer: dragged })
                );
            },
        },
        {
            content: "The receipt is listed on the dialog",
            trigger: ".modal .o_attachment:contains('receipt.txt')",
        },
        {
            content: "One press keys it and submits it",
            trigger: ".modal footer button[name='action_submit_close']",
            run: "click",
        },
        {
            content: "It is on the file, already submitted",
            trigger: ".o_field_widget[name='expense_ids'] .o_data_row:contains('Terminal handling')",
        },
        {
            content: "and the file needed no saving of its own",
            trigger: ".o_form_view:not(:has(.o_form_button_save:enabled))",
        },
    ],
});
