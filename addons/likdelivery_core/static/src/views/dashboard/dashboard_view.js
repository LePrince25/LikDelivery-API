/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

import { Component, onWillStart, useState } from "@odoo/owl";

const NUMBER_FORMAT = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const KPI_CARDS = [
    { key: "users", label: "Utilisateurs", model: "likdelivery.user" },
    { key: "orders", label: "Commandes", model: "likdelivery.order" },
    { key: "delivery_runs", label: "Courses", model: "likdelivery.delivery.run" },
    { key: "courier_requests", label: "Courses colis", model: "likdelivery.courier.request" },
    {
        key: "pending_validation",
        label: "Validations en attente",
        model: "likdelivery.user",
        domain: [
            ["lik_role", "in", ["fournisseur", "societe"]],
            ["lik_validated_by_admin", "=", false],
        ],
    },
    { key: "today_orders", label: "Commandes du jour", model: "likdelivery.order" },
    { key: "total_revenue", label: "Revenu total (XOF)", model: "likdelivery.order" },
];

/**
 * Platform activity dashboard: KPI cards, 14-day order volume, order states
 * and top suppliers. Every tile opens the matching list view.
 */
export class LikdeliveryDashboardView extends Component {
    static template = "likdelivery_core.DashboardView";
    static props = { ...standardActionServiceProps };

    setup() {
        this.actionService = useService("action");
        this.state = useState({ data: null, loading: true });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            this.state.data = await rpc("/likdelivery/dashboard/data");
        } finally {
            this.state.loading = false;
        }
    }

    get cards() {
        const stats = this.state.data ? this.state.data.stats : {};
        return KPI_CARDS.map((card) => ({ ...card, value: stats[card.key] }));
    }

    get statuses() {
        if (!this.state.data) {
            return [];
        }
        const labels = this.state.data.status_labels || {};
        return Object.entries(this.state.data.status_counts).map(([state, count]) => ({
            state,
            count,
            label: labels[state] || state,
        }));
    }

    format(value) {
        return NUMBER_FORMAT.format(value || 0);
    }

    /** Bar height as a percentage of the busiest day (2% keeps a zero visible). */
    barHeight(total) {
        const max = this.state.data ? this.state.data.max_day_total : 0;
        return max ? `${Math.max(2, Math.round((total / max) * 100))}%` : "0%";
    }

    openModel(model, name, domain = []) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            name,
            domain,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }
}

registry.category("actions").add("likdelivery_dashboard_view", LikdeliveryDashboardView);
