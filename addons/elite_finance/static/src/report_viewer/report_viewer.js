import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/**
 * A report, shown at once (owner, 11/10/2026).
 *
 * Enterprise opens its reports straight on the figures, with the filters
 * on the page; the OCA reports ask their questions in a dialog first.
 * This action creates the OCA wizard with its own defaults - the fiscal
 * year to date, posted entries - and shows the HTML report it would have
 * shown after View, under a bar carrying the quick filters. A change
 * writes the wizard and renders again; "More filters" opens the wizard's
 * full form in a dialog whose Apply button does the same; PDF and Excel
 * export what is on screen.
 *
 * The HTML report is the one Odoo renders for a qweb-html action: the
 * URL is built the way the web client builds it (webclient/actions/
 * reports/utils.js), with the wizard's data as `options`.
 */
export class ReportViewer extends Component {
    static template = "elite_finance.ReportViewer";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        const context = this.props.action.context || {};
        this.model = context.wizard_model;
        this.partnerType = context.elite_finance_partner_type || false;
        this.title = this.props.action.name || this.props.action.display_name || "";
        this.state = useState({
            wizardId: false,
            fields: [],
            filters: {},
            url: false,
            busy: true,
            version: 0,
        });
        onWillStart(() => this.create());
    }

    async create() {
        const context = {};
        if (this.partnerType) {
            context.elite_finance_partner_type = this.partnerType;
        }
        const [wizardId] = await this.orm.create(this.model, [{}], { context });
        this.state.wizardId = wizardId;
        await this.refresh();
    }

    async refresh() {
        this.state.busy = true;
        const state = await this.orm.call(this.model, "elite_finance_viewer_state", [
            [this.state.wizardId],
        ]);
        this.state.fields = state.fields;
        this.state.filters = state.filters;
        const options = encodeURIComponent(JSON.stringify(state.data || {}));
        const context = encodeURIComponent(
            JSON.stringify({ ...user.context, ...(state.context || {}) })
        );
        this.state.version += 1;
        this.state.url = `/report/html/${state.report_name}?options=${options}&context=${context}&v=${this.state.version}`;
        this.state.busy = false;
    }

    onFilterChange(name, value) {
        this.state.filters[name] = value || false;
    }

    async apply() {
        await this.orm.write(this.model, [this.state.wizardId], { ...this.state.filters });
        await this.refresh();
    }

    openFilters() {
        this.dialog.add(FormViewDialog, {
            resModel: this.model,
            resId: this.state.wizardId,
            title: _t("Filters: %s", this.title),
            context: { elite_finance_viewer: true },
            onRecordSaved: () => this.refresh(),
        });
    }

    async exportAs(kind) {
        const method = kind === "xlsx" ? "button_export_xlsx" : "button_export_pdf";
        const action = await this.orm.call(this.model, method, [[this.state.wizardId]], {
            context: { discard_logo_check: true },
        });
        await this.action.doAction(action);
    }
}

registry.category("actions").add("elite_finance_report_viewer", ReportViewer);
