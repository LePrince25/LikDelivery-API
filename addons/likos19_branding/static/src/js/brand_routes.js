/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { router, routerBus, startRouter } from "@web/core/browser/router";
import { registry } from "@web/core/registry";
import { NavBar } from "@web/webclient/navbar/navbar";
import { WebClient } from "@web/webclient/webclient";
import { Many2One } from "@web/views/fields/many2one/many2one";
import "@web/core/pwa/pwa_service";

const LIKOS_ROOT = "/likos";
const ODOO_ROOT = "/odoo";

function isWebclientPath(path) {
    return (
        path === LIKOS_ROOT ||
        path === ODOO_ROOT ||
        path === "/web" ||
        path.startsWith(`${LIKOS_ROOT}/`) ||
        path.startsWith(`${ODOO_ROOT}/`)
    );
}

function toLikosPath(path) {
    if (path === ODOO_ROOT || path.startsWith(`${ODOO_ROOT}/`) || path.startsWith(`${ODOO_ROOT}?`)) {
        return `${LIKOS_ROOT}${path.slice(ODOO_ROOT.length)}`;
    }
    return path;
}

const originalStateToUrl = router.stateToUrl.bind(router);
const originalUrlToState = router.urlToState.bind(router);

router.stateToUrl = (state) => toLikosPath(originalStateToUrl(state));
router.urlToState = (urlObj) => {
    const href = urlObj instanceof URL ? urlObj.href : String(urlObj);
    const url = new URL(href, browser.location.origin);
    if (url.pathname === LIKOS_ROOT || url.pathname.startsWith(`${LIKOS_ROOT}/`)) {
        url.pathname = `${ODOO_ROOT}${url.pathname.slice(LIKOS_ROOT.length) || ""}`;
    }
    return originalUrlToState(url);
};

if (browser.location.pathname === ODOO_ROOT || browser.location.pathname.startsWith(`${ODOO_ROOT}/`)) {
    const next = `${toLikosPath(browser.location.pathname)}${browser.location.search}${browser.location.hash}`;
    browser.history.replaceState(browser.history.state, "", next);
}
startRouter();

browser.addEventListener("click", (ev) => {
    if (ev.defaultPrevented || ev.target.closest("[contenteditable]")) {
        return;
    }
    const anchor = ev.target.closest("a");
    const href = anchor?.getAttribute("href");
    if (!href || href.startsWith("#")) {
        return;
    }
    let url;
    try {
        url = new URL(anchor.href);
    } catch {
        return;
    }
    const here = browser.location.pathname;
    if (browser.location.host !== url.host || !isWebclientPath(here) || !isWebclientPath(url.pathname) || anchor.target === "_blank") {
        return;
    }
    ev.preventDefault();
    if (url.pathname === ODOO_ROOT || url.pathname.startsWith(`${ODOO_ROOT}/`)) {
        url.pathname = toLikosPath(url.pathname);
    }
    const nextState = router.urlToState(url);
    router.replaceState(nextState, { replace: true, sync: true });
    routerBus.trigger("ROUTE_CHANGE");
});

patch(NavBar.prototype, {
    getMenuItemHref(payload) {
        return `${LIKOS_ROOT}/${payload.actionPath || "action-" + payload.actionID}`;
    },
});

patch(Many2One.prototype, {
    get linkHref() {
        return toLikosPath(super.linkHref);
    },
});

patch(WebClient.prototype, {
    async registerServiceWorker() {
        if (!navigator.serviceWorker) {
            this.serviceWorkerActivatedDeferred.resolve();
            return;
        }
        try {
            const registration = await navigator.serviceWorker.register("/web/service-worker.js", {
                scope: LIKOS_ROOT,
            });
            const worker = registration.installing || registration.waiting || registration.active;
            if (!worker || worker.state === "activated") {
                this.serviceWorkerActivatedDeferred.resolve();
                return;
            }
            worker.addEventListener("statechange", (event) => {
                if (event.target.state === "activated") {
                    this.serviceWorkerActivatedDeferred.resolve();
                }
            });
        } catch (error) {
            console.error("LikOS service worker registration failed", error);
            this.serviceWorkerActivatedDeferred.resolve();
        }
    },
});

const services = registry.category("services");
if (services.contains("pwa")) {
    const originalPwa = services.get("pwa");
    services.add(
        "pwa",
        {
            ...originalPwa,
            start(env, deps) {
                const state = originalPwa.start(env, deps);
                if (state && state.startUrl === ODOO_ROOT) {
                    state.startUrl = LIKOS_ROOT;
                }
                return state;
            },
        },
        { force: true }
    );
}
