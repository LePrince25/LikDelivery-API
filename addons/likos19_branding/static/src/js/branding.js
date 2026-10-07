/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";
import { session } from "@web/session";

function applyFavicon(url, type) {
    if (!url) {
        return;
    }
    const links = document.querySelectorAll("link[rel='shortcut icon'], link[rel='icon']");
    if (!links.length) {
        const link = document.createElement("link");
        link.rel = "icon";
        link.setAttribute("sizes", "any");
        if (type) {
            link.type = type;
        }
        link.href = url;
        document.head.appendChild(link);
        return;
    }
    for (const link of links) {
        if (type) {
            link.type = type;
        }
        if (!link.getAttribute("sizes")) {
            link.setAttribute("sizes", "any");
        }
        link.href = url;
    }
}

function applyAppLogo(url, type) {
    if (!url) {
        return;
    }
    document.documentElement.style.setProperty("--likos-app-logo", `url("${url}")`);
    const images = document.querySelectorAll("[data-likos-app-logo]");
    for (const image of images) {
        image.src = url;
        image.classList.toggle("is-svg", type === "image/svg+xml");
        image.removeAttribute("hidden");
    }
}

const branding = session.likos_branding || {};
applyFavicon(branding.favicon, branding.favicon_type);
applyAppLogo(branding.app_logo, branding.app_logo_type);
if (branding.app_name) {
    document.title = branding.app_name;
}

patch(NavBar.prototype, {
    get brandingAppLogo() {
        return session.likos_branding?.app_logo || "/likos/branding/app-logo";
    },
});
