import { Component, onWillStart, useRef, useState } from "@odoo/owl";
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
 * on the page as pill buttons; the OCA reports ask their questions in a
 * dialog first. This action creates the OCA wizard with its own defaults
 * - the fiscal year to date, posted entries - and shows the HTML report
 * it would have shown after View, under a bar in Enterprise's shape: a
 * search box that filters the lines on screen, a period button with
 * presets and custom dates, a posted-or-all switch, More filters for the
 * wizard's full form in a dialog, and PDF / Excel of what is on screen.
 *
 * The HTML report is the one Odoo renders for a qweb-html action: the
 * URL is built the way the web client builds it (webclient/actions/
 * reports/utils.js), with the wizard's data as `options`.
 */

function iso(date) {
    return date.toISOString().slice(0, 10);
}

function presetsFor(hasRange) {
    const today = new Date();
    const y = today.getFullYear();
    const m = today.getMonth();
    const q = Math.floor(m / 3);
    const endOf = (year, month) => new Date(Date.UTC(year, month + 1, 0));
    const startOf = (year, month) => new Date(Date.UTC(year, month, 1));
    if (hasRange) {
        return [
            { key: "month", label: _t("This Month"), from: startOf(y, m), to: endOf(y, m) },
            { key: "quarter", label: _t("This Quarter"), from: startOf(y, q * 3), to: endOf(y, q * 3 + 2) },
            { key: "year", label: _t("This Year"), from: startOf(y, 0), to: endOf(y, 11) },
            { key: "lastmonth", label: _t("Last Month"), from: startOf(y, m - 1), to: endOf(y, m - 1) },
            { key: "lastquarter", label: _t("Last Quarter"), from: startOf(y, q * 3 - 3), to: endOf(y, q * 3 - 1) },
            { key: "lastyear", label: _t("Last Year"), from: startOf(y - 1, 0), to: endOf(y - 1, 11) },
        ];
    }
    return [
        { key: "today", label: _t("Today"), at: new Date(Date.UTC(y, m, today.getDate())) },
        { key: "endmonth", label: _t("End of Last Month"), at: endOf(y, m - 1) },
        { key: "endquarter", label: _t("End of Last Quarter"), at: endOf(y, q * 3 - 1) },
        { key: "endyear", label: _t("End of Last Year"), at: endOf(y - 1, 11) },
    ];
}

export class ReportViewer extends Component {
    static template = "elite_finance.ReportViewer";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.frame = useRef("frame");
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
            menu: false,        // which pill's menu is open: "period" | "entries" | false
            custom: false,      // the period menu shows the date inputs
            search: "",
        });
        onWillStart(() => this.create());
    }

    // ----------------------------------------------------------- data
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
        this.state.menu = false;
    }

    async apply(values) {
        await this.orm.write(this.model, [this.state.wizardId], values || { ...this.state.filters });
        await this.refresh();
    }

    // -------------------------------------------------------- the bar
    get hasRange() {
        return this.state.fields.some((f) => f.name === "date_from") && this.state.fields.some((f) => f.name === "date_to");
    }

    get hasAt() {
        return this.state.fields.some((f) => f.name === "date_at");
    }

    get hasEntries() {
        return this.state.fields.some((f) => f.name === "target_move");
    }

    get presets() {
        return presetsFor(this.hasRange);
    }

    get periodLabel() {
        const f = this.state.filters;
        if (this.hasRange && f.date_from && f.date_to) {
            return `${f.date_from} → ${f.date_to}`;
        }
        if (this.hasAt && f.date_at) {
            return _t("As at %s", f.date_at);
        }
        return _t("Period");
    }

    get entriesLabel() {
        return this.state.filters.target_move === "all" ? _t("All Entries") : _t("Posted Entries");
    }

    toggleMenu(name) {
        this.state.menu = this.state.menu === name ? false : name;
        this.state.custom = false;
    }

    async pickPreset(preset) {
        const values = preset.at ? { date_at: iso(preset.at) } : { date_from: iso(preset.from), date_to: iso(preset.to) };
        Object.assign(this.state.filters, values);
        await this.apply(values);
    }

    onDate(name, value) {
        this.state.filters[name] = value || false;
    }

    async applyCustom() {
        const values = {};
        for (const name of ["date_from", "date_to", "date_at"]) {
            if (name in this.state.filters) {
                values[name] = this.state.filters[name];
            }
        }
        await this.apply(values);
    }

    async pickEntries(value) {
        this.state.filters.target_move = value;
        await this.apply({ target_move: value });
    }

    openFilters() {
        this.state.menu = false;
        this.dialog.add(FormViewDialog, {
            resModel: this.model,
            resId: this.state.wizardId,
            title: _t("Filters: %s", this.title),
            context: { elite_finance_viewer: true },
            onRecordSaved: () => this.refresh(),
        });
    }

    async exportAs(kind) {
        this.state.menu = false;
        const method = kind === "xlsx" ? "button_export_xlsx" : "button_export_pdf";
        const action = await this.orm.call(this.model, method, [[this.state.wizardId]], {
            context: { discard_logo_check: true },
        });
        await this.action.doAction(action);
    }

    // The search box filters the lines already on screen: the report is
    // ours to read (same origin), so the rows that do not mention the
    // text are hidden, the headers and totals stay.
    onSearch(value) {
        this.state.search = value;
        this.filterRows();
    }

    onFrameLoad() {
        this.filterRows();
    }

    filterRows() {
        const doc = this.frame.el && this.frame.el.contentDocument;
        if (!doc) {
            return;
        }
        const needle = (this.state.search || "").trim().toLowerCase();
        for (const row of doc.querySelectorAll(".act_as_row.lines")) {
            const hit = !needle || row.textContent.toLowerCase().includes(needle);
            row.style.display = hit ? "" : "none";
        }
    }
}

registry.category("actions").add("elite_finance_report_viewer", ReportViewer);
