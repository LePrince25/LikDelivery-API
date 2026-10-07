/** @odoo-module **/

/**
 * Mini implémentation de `createComponent` pour permettre aux modules SAGCOP
 * d'enregistrer leurs dashboards via le registre d'actions client d'Odoo.
 *
 * Le vrai `likos_owl_framework` (LIKDIGITALL/likos-owl-framework) n'est pas
 * accessible (dépôt GitHub privé, pas de copie locale, pas dans l'image Docker).
 * Ce stub reproduit l'API attendue par les modules SAGCOP en s'appuyant sur
 * `useState` (réactivité Owl v2) et l'injection de services Odoo.
 *
 * Limites connues : les vrais composants visuels du framework (KPI cards,
 * graphiques, document viewer, etc.) ne sont pas fournis. Chaque dashboard
 * utilise son template QWeb propre (déjà présent dans le module SAGCOP) ;
 * certains widgets internes référencés par ces templates peuvent ne pas
 * s'afficher si le template en question dépend d'un sous-composant Owl
 * uniquement disponible dans le vrai `likos_owl_framework`.
 */

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const _registry = registry.category("actions");

/**
 * Helper : si une valeur est `null` ou `undefined`, retourne la valeur de
 * repli passée en argument. Sinon retourne la valeur d'origine. Utilisé pour
 * protéger les expressions `t-foreach` des templates SAGCOP qui itèrent sur
 * des propriétés d'état non encore chargées.
 */
export function ensureArray(value) {
    if (value === null || value === undefined) return [];
    if (Array.isArray(value)) return value;
    return [];
}

export function ensureObject(value) {
    if (value === null || value === undefined) return {};
    if (typeof value === "object") return value;
    return {};
}

export function ensureString(value, fallback = "") {
    if (value === null || value === undefined) return fallback;
    return String(value);
}

/**
 * Crée un composant Owl, l'enregistre dans le registre `actions` sous le tag
 * donné, et fournit une API compatible avec ce qu'attendent les modules
 * SAGCOP.
 *
 * Champs acceptés dans `spec` :
 *  - name        : nom interne (debug uniquement — non assigné à la classe)
 *  - template    : nom QWeb du template
 *  - tag         : tag ir.actions.client
 *  - state       : état initial (sera enveloppé dans useState)
 *  - methods     : méthodes attachées à l'instance (this = composant)
 *  - computed    : getters Owl — propriétés calculées utilisables dans le template
 *  - onInit      : hook de setup (équivalent du setup Owl)
 *  - onWillStart : hook Owl willStart
 *  - services    : liste des services Odoo à injecter (orm, action, etc.)
 */
export function createComponent(spec) {
    const {
        name,
        template,
        tag,
        state: initialState = {},
        methods = {},
        computed = {},
        onInit,
        onWillStart,
        services: requestedServices = ["orm", "notification", "action", "user", "dialog"],
    } = spec;

    if (_registry.contains(tag)) {
        return;
    }

    class LikosComponent extends Component {
        setup() {
            // État réactif Owl
            this.state = useState({ ...initialState });

            // Les `t-foreach` des templates SAGCOP itèrent directement sur
            // des propriétés de `state` (sans guard `t-if state.data`). Si la
            // propriété est absente (undefined) Owl lève
            // `Invalid loop expression`. On force donc toutes les valeurs
            // d'initialisation à leur équivalent non-undefined.
            for (const [key, value] of Object.entries(this.state)) {
                if (value === null || value === undefined) {
                    this.state[key] = typeof key === "string" && key.endsWith("s") ? [] : null;
                }
            }

            // Services Odoo
            for (const serviceName of requestedServices) {
                try {
                    this[serviceName] = useService(serviceName);
                } catch (e) {
                    // Le service n'existe pas — on continue sans planter.
                }
            }

            // Raccourcis pratiques pour les dashboards SAGCOP
            this.call = (...args) => this.orm ? this.orm.call(...args) : Promise.reject("orm not available");
            this.notifyError = (msg) => this.notification ? this.notification.add(msg, { type: "danger" }) : console.error(msg);
            this.notifySuccess = (msg) => this.notification ? this.notification.add(msg, { type: "success" }) : console.log(msg);
            this.openList = (model, domain) =>
                this.action
                    ? this.action.doAction({
                          type: "ir.actions.act_window",
                          res_model: model,
                          views: [[false, "list"], [false, "form"]],
                          domain: domain || [],
                      })
                    : Promise.reject("action service not available");

            // Rattache les méthodes spécifiées par l'appelant
            for (const [key, fn] of Object.entries(methods)) {
                this[key] = fn;
            }

            // Définit les getters pour les computed properties
            for (const [key, fn] of Object.entries(computed)) {
                Object.defineProperty(this, key, {
                    get: () => fn.call(this),
                    configurable: true,
                });
            }

            // Hook d'init
            if (typeof onInit === "function") {
                onInit.call(this);
            }
        }

        async willStart() {
            if (typeof onWillStart === "function") {
                return onWillStart.call(this);
            }
        }
    }
    LikosComponent.template = template;
    LikosComponent.components = {};
    LikosComponent.props = { "*": true };

    // Note : on n'assigne pas `LikosComponent.name` car le `name` d'une classe
    // ES6 est read-only. Le nom interne est uniquement utilisé pour le debug
    // et n'a pas d'incidence sur le runtime Owl.

    _registry.add(tag, LikosComponent, { force: false });
}
