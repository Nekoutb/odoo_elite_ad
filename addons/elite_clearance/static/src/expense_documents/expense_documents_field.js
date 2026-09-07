import { registry } from "@web/core/registry";
import { useDropzone } from "@web/core/dropzone/dropzone_hook";
import { useFileUploader } from "@web/core/utils/files";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";
import { useRef } from "@odoo/owl";

/**
 * The expense dialog's documents.
 *
 * The standard attachment list and Upload button, plus a drop zone over the
 * whole form the field sits in - in the file's expense dialog, the dialog
 * itself. A receipt dragged anywhere onto it is uploaded exactly as the
 * Upload button would upload it (same route, same attachment record) and
 * listed with the others. Owner spec 06/09/2026.
 */
export class ExpenseDocumentsField extends Many2ManyBinaryField {
    static template = "elite_clearance.ExpenseDocumentsField";

    setup() {
        super.setup();
        this.rootRef = useRef("root");
        this.uploadFiles = useFileUploader();
        const rootRef = this.rootRef;
        // The target is the dialog's form, so nobody has to aim at one small
        // box. Outside a dialog the field is its own target: the record's
        // page has a chatter, and the chatter already takes drops.
        const targetRef = {
            get el() {
                const el = rootRef.el;
                return el ? el.closest(".modal .o_form_view") || el : null;
            },
        };
        useDropzone(targetRef, (ev) => this.onDrop(ev), "", () => !this.props.readonly);
    }

    async onDrop(ev) {
        const files = ev.dataTransfer ? [...ev.dataTransfer.files] : [];
        if (!files.length) {
            return;
        }
        const uploaded = await this.uploadFiles("/web/binary/upload_attachment", {
            csrf_token: odoo.csrf_token,
            ufile: files,
            model: this.props.record.resModel,
            id: this.props.record.resId || 0,
        });
        if (uploaded) {
            await this.onFileUploaded(uploaded);
        }
    }
}

registry.category("fields").add("clearance_expense_documents", {
    ...many2ManyBinaryField,
    component: ExpenseDocumentsField,
});
