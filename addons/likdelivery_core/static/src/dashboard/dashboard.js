/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

import { Component, onWillStart, useState } from "@odoo/owl";

import { LikAllocation, LikAreaChart, LikDonut, LikPairs, LikSparkline } from "./charts";

/**
 * Tableau de bord de l'application Livraison.
 *
 * Une seule mise en scene pour tous les roles : c'est likdelivery.dashboard
 * qui decide des indicateurs, des panneaux, du fil d'activite et des tableaux
 * selon le role du compte connecte. Chaque indicateur est l'entree de la page
 * qui le detaille, si le role voit cette page. Le clic sur une ligne ouvre le
 * formulaire.
 */
export class LikDeliveryDashboard extends Component {
    static template = "likdelivery_core.Dashboard";
    static components = { LikAllocation, LikAreaChart, LikDonut, LikPairs, LikSparkline };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({ data: null, days: 30, loading: false });
        onWillStart(() => this.load(30));
    }

    async load(days) {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("likdelivery.dashboard", "get_data", [days]);
            this.state.days = days;
        } finally {
            this.state.loading = false;
        }
    }

    get data() {
        return this.state.data;
    }

    setPeriod(days) {
        if (days !== this.state.days) {
            this.load(days);
        }
    }

    openRecord(model, resId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openList(model) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openStat(stat) {
        // L'id de l'action du menu de destination, pas une action rejouee ici :
        // le domaine, le contexte et les vues enregistres sur l'action font le
        // filtre du role. Un indicateur sans page reste muet.
        if (stat.action_id) {
            this.actionService.doAction(stat.action_id);
        }
    }
}

registry.category("actions").add("likdelivery_dashboard", LikDeliveryDashboard);
