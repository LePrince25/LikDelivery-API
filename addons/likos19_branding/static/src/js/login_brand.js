/** @odoo-module **/

const APP_CONFIG_URL = "/likos/app-config";

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

function applyLoginLogo(url, type) {
    if (!url) {
        return;
    }
    const images = document.querySelectorAll("[data-likos-login-logo], img.likos-login-logo");
    for (const image of images) {
        image.src = url;
        image.classList.toggle("is-svg", type === "image/svg+xml");
        image.removeAttribute("hidden");
    }
}

async function loadPublicBranding() {
    try {
        const response = await fetch(APP_CONFIG_URL, {
            credentials: "same-origin",
            headers: { Accept: "application/json" },
        });
        if (!response.ok) {
            return;
        }
        const payload = await response.json();
        const appName = typeof payload.app_name === "string" ? payload.app_name.trim() : "";
        if (appName) {
            for (const target of document.querySelectorAll("[data-likos-app-name]")) {
                target.textContent = appName;
            }
            document.title = appName;
        }
        applyFavicon(payload.favicon, payload.favicon_type);
        applyLoginLogo(payload.login_logo, payload.login_logo_type);
    } catch {
        // Keep the server-rendered fallback when the public endpoint is unavailable.
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadPublicBranding, { once: true });
} else {
    loadPublicBranding();
}
