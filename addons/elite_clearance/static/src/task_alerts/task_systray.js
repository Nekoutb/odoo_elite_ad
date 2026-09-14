import { Component, onWillStart, onWillUnmount, useExternalListener, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * The bell at the top right: what is waiting on the person reading the
 * screen, and a short beep the moment something lands there.
 *
 * Odoo's own systray counters are refreshed when the page is, which is no
 * use to somebody who has had the same screen open since nine o'clock.
 * The server pushes each new task down the bus (clearance.task
 * _notify_assignment), so the count moves, a toast offers the record and
 * the beep says to look. Clicking a row opens that record; there is no
 * going back to a list first.
 *
 * clearance.task narrows itself to the reader in its own _search, so this
 * asks for "everything" and receives only what this person can act on.
 */
export class ClearanceTaskSystray extends Component {
    static template = "elite_clearance.TaskSystray";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.bus = useService("bus_service");
        this.state = useState({ open: false, count: 0, tasks: [] });

        this.onTask = this.onTask.bind(this);
        this.bus.subscribe("elite_clearance.task", this.onTask);
        onWillUnmount(() => {
            this.bus.unsubscribe?.("elite_clearance.task", this.onTask);
        });
        // Clicking anywhere else closes it. The toggle's own click has a
        // target INSIDE the bell, so opening never closes it again.
        useExternalListener(window, "click", (ev) => {
            if (this.state.open && !ev.target.closest(".o_clearance_tasks")) {
                this.state.open = false;
            }
        });
        onWillStart(() => this.load());
    }

    async load() {
        try {
            const tasks = await this.orm.searchRead(
                "clearance.task",
                [],
                ["name", "kind_label", "detail", "res_model", "res_id"],
                { limit: 15 }
            );
            this.state.tasks = tasks;
            this.state.count = await this.orm.searchCount("clearance.task", []);
        } catch {
            // A bell that cannot count is not a reason to break the top
            // of everybody's screen.
            this.state.tasks = [];
            this.state.count = 0;
        }
    }

    toggle() {
        this.state.open = !this.state.open;
        if (this.state.open) {
            this.load();
        }
    }

    onTask(payload) {
        this.load();
        this.beep();
        this.notification.add(payload.detail || payload.name, {
            title: payload.title,
            type: "info",
            buttons: [
                {
                    name: _t("Open"),
                    onClick: () => this.openTask(payload),
                },
            ],
        });
    }

    openTask(task) {
        this.state.open = false;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: task.res_model,
            res_id: task.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAll() {
        this.state.open = false;
        this.action.doAction("elite_clearance.action_clearance_tasks");
    }

    /** A short, quiet tone. Long enough to hear, short enough to forgive. */
    beep() {
        try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) {
                return;
            }
            this.audio = this.audio || new Ctx();
            if (this.audio.state === "suspended") {
                this.audio.resume();
            }
            const now = this.audio.currentTime;
            const oscillator = this.audio.createOscillator();
            const gain = this.audio.createGain();
            oscillator.type = "sine";
            oscillator.frequency.value = 880;
            gain.gain.setValueAtTime(0.0001, now);
            gain.gain.exponentialRampToValueAtTime(0.06, now + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.18);
            oscillator.connect(gain).connect(this.audio.destination);
            oscillator.start(now);
            oscillator.stop(now + 0.2);
        } catch {
            // Some browsers refuse to make a sound before the page has
            // been clicked. The toast and the count still arrive.
        }
    }
}

registry
    .category("systray")
    .add("elite_clearance.tasks", { Component: ClearanceTaskSystray }, { sequence: 30 });
