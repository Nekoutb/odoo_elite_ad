import { registry } from "@web/core/registry";
import { useDropzone } from "@web/core/dropzone/dropzone_hook";
import { useFileUploader } from "@web/core/utils/files";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";
import { useRef } from "@odoo/owl";

/**
 * Supporting documents, with a drop zone over the area they belong to.
 *
 * The standard attachment list and Upload button, plus a region of the
 * screen that takes a dropped file and uploads it exactly as the Upload
 * button would. Which region is the point: nobody should have to aim at a
 * small box.
 *
 *   options="{'dropzone': '.o_clearance_documents_area'}"
 *     the nearest ancestor matching that selector - use it to make a
 *     whole block of a form (the document checklist, say) the target.
 *   no option
 *     inside a dialog, the dialog's whole form; outside one, the field
 *     itself, because the record's page has a chatter that takes drops
 *     of its own.
 *
 * Owner spec 06/09/2026 (the expense dialog), widened 08/09/2026 to every
 * area documents can be dropped on.
 */
export class ClearanceDocumentsField extends Many2ManyBinaryField {
    static template = "elite_clearance.ClearanceDocumentsField";
    static props = {
        ...Many2ManyBinaryField.props,
        dropzoneSelector: { type: String, optional: true },
    };

    setup() {
        super.setup();
        this.rootRef = useRef("root");
        this.uploadFiles = useFileUploader();
        const rootRef = this.rootRef;
        const selector = this.props.dropzoneSelector;
        const targetRef = {
            get el() {
                const el = rootRef.el;
                if (!el) {
                    return null;
                }
                return el.closest(selector || ".modal .o_form_view") || el;
            },
        };
        useDropzone(targetRef, (ev) => this.onDrop(ev), "", () => !this.props.readonly);
    }

    get dropHint() {
        return this.props.dropzoneSelector
            ? "or drop files anywhere in this section"
            : "or drop files anywhere on this dialog";
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

export const clearanceDocumentsField = {
    ...many2ManyBinaryField,
    component: ClearanceDocumentsField,
    supportedOptions: [
        ...(many2ManyBinaryField.supportedOptions || []),
        { label: "Drop zone", name: "dropzone", type: "string" },
    ],
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...many2ManyBinaryField.extractProps(fieldInfo, dynamicInfo),
        dropzoneSelector: fieldInfo.options.dropzone,
    }),
};

registry.category("fields").add("clearance_documents", clearanceDocumentsField);
