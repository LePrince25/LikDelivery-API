
const API = "";
let state = { user: null, cart: {}, products: [], categories: [], suppliers: [], installPrompt: null };
let mapInstance = null;
let markers = [];
// Pending client action after login/register (e.g. add to cart)
let pendingClientAction = null;

// --- /api/v1 shim: translate legacy Flask paths to the Odoo REST API ---
const API_PATH_MAP = [
  // auth
  [/^\/api\/login$/, "/api/v1/auth/login"],
  [/^\/api\/logout$/, "/api/v1/auth/logout"],
  [/^\/api\/register$/, "/api/v1/auth/register"],
  [/^\/api\/me$/, "/api/v1/auth/me"],
  [/^\/api\/profile$/, "/api/v1/auth/profile"],
  // catalogue (client)
  [/^\/api\/categories$/, "/api/v1/client/catalog/categories"],
  [/^\/api\/suppliers$/, "/api/v1/client/catalog/suppliers"],
  [/^\/api\/products\/(\d+)$/, "/api/v1/client/catalog/products/$1"],
  [/^\/api\/products$/, "/api/v1/client/catalog/products"],
  [/^\/api\/supplier\/opening-hours\/(\d+)$/, "/api/v1/client/catalog/suppliers/$1/opening-hours"],
  [/^\/api\/societes$/, "/api/v1/client/catalog/societes"],
  [/^\/api\/livreurs$/, "/api/v1/client/catalog/livreurs"],
  [/^\/api\/recommended-livreurs$/, "/api/v1/client/catalog/recommended-livreurs"],
  [/^\/api\/estimate-delivery$/, "/api/v1/client/estimate-delivery"],
  // cart & orders (client)
  [/^\/api\/cart\/checkout-preview$/, "/api/v1/client/cart/checkout-preview"],
  [/^\/api\/cart$/, "/api/v1/client/cart"],
  [/^\/api\/orders\/multi$/, "/api/v1/client/orders/multi"],
  [/^\/api\/orders\/payment$/, "/api/v1/client/orders/payment"],
  [/^\/api\/orders\/(\d+)\/cancel$/, "/api/v1/client/orders/$1/cancel"],
  [/^\/api\/orders\/(\d+)\/pickup-action$/, "/api/v1/client/orders/$1/pickup-action"],
  [/^\/api\/orders\/(\d+)\/assign-livreur$/, "/api/v1/merchant/orders/$1/assign-driver"],
  [/^\/api\/orders\/(\d+)$/, "/api/v1/client/orders/$1"],
  [/^\/api\/courier-requests$/, "/api/v1/client/courier-requests"],
  [/^\/api\/rate$/, "/api/v1/client/rate"],
  // notifications & payments (client)
  [/^\/api\/notifications\/(\d+)\/read$/, "/api/v1/client/notifications/$1/read"],
  [/^\/api\/notifications$/, "/api/v1/client/notifications"],
  [/^\/api\/payments\/initiate$/, "/api/v1/client/payments/initiate"],
  [/^\/api\/payments\/([^/]+)\/status$/, "/api/v1/client/payments/$1/status"],
  [/^\/api\/payments\/([^/]+)\/confirm$/, "/api/v1/client/payments/$1/confirm"],
  [/^\/api\/simulate-payment$/, "/api/v1/client/payments/simulate"],
  // merchant (fournisseur / societe)
  [/^\/api\/supplier\/opening-hours$/, "/api/v1/merchant/opening-hours"],
  [/^\/api\/supplier\/kyc$/, "/api/v1/merchant/kyc"],
  [/^\/api\/supplier\/livreurs$/, "/api/v1/merchant/shop-drivers"],
  [/^\/api\/supplier\/orders\/(\d+)\/status$/, "/api/v1/merchant/orders/$1/status"],
  [/^\/api\/supplier\/orders\/(\d+)\/init-handover$/, "/api/v1/merchant/orders/$1/init-handover"],
  [/^\/api\/supplier\/sales-history$/, "/api/v1/merchant/sales-history"],
  [/^\/api\/supplier\/products\/(\d+)\/image$/, "/api/v1/merchant/products/$1/image"],
  [/^\/api\/supplier\/products\/(\d+)$/, "/api/v1/merchant/products/$1"],
  [/^\/api\/supplier\/products$/, "/api/v1/merchant/products"],
  // fleet (societe)
  [/^\/api\/societe\/livreurs\/(\d+)$/, "/api/v1/merchant/fleet/drivers/$1"],
  [/^\/api\/societe\/livreurs$/, "/api/v1/merchant/fleet/drivers"],
  [/^\/api\/societe\/orders$/, "/api/v1/merchant/fleet/orders"],
  // driver (livreur)
  [/^\/api\/livreur\/available-orders$/, "/api/v1/driver/available-orders"],
  [/^\/api\/livreur\/orders\/(\d+)\/claim$/, "/api/v1/driver/orders/$1/claim"],
  [/^\/api\/livreur\/missions\/(\d+)\/action$/, "/api/v1/driver/missions/$1/action"],
  [/^\/api\/livreur\/missions\/(\d+)\/status$/, "/api/v1/driver/missions/$1/status"],
  [/^\/api\/livreur\/missions$/, "/api/v1/driver/missions"],
  [/^\/api\/livreur\/location$/, "/api/v1/driver/location"],
  [/^\/api\/validate-delivery$/, "/api/v1/driver/validate-delivery"],
];

function mapApiUrl(url) {
  const str = String(url);
  const qIdx = str.indexOf("?");
  const path = qIdx >= 0 ? str.slice(0, qIdx) : str;
  const qs = qIdx >= 0 ? str.slice(qIdx) : "";
  const role = state.user && state.user.role;
  // Wallet endpoints are role-dependent (fournisseur/societe → merchant, livreur → driver).
  if (path === "/api/wallet" || path === "/api/wallet/withdraw") {
    const base = role === "livreur" ? "/api/v1/driver/wallet" : "/api/v1/merchant/wallet";
    return (path === "/api/wallet/withdraw" ? base + "/withdraw" : base) + qs;
  }
  // Fournisseurs / societes list their sales through the merchant API.
  if (path === "/api/orders") {
    return (["fournisseur", "societe", "admin"].includes(role)
      ? "/api/v1/merchant/orders"
      : "/api/v1/client/orders") + qs;
  }
  // Admin & test-notification endpoints have no /api/v1 equivalent:
  // administration now lives in the Odoo back-office (/web).
  if (path.startsWith("/api/admin") || path === "/api/notifications/send-test") {
    console.warn("[api] no /api/v1 equivalent for", path, "— use the Odoo back-office (/web)");
    return null;
  }
  for (const [pattern, target] of API_PATH_MAP) {
    if (pattern.test(path)) return path.replace(pattern, target) + qs;
  }
  return url;
}

async function api(url, opts={}) {
  const mapped = mapApiUrl(url);
  if (!mapped) {
    throw new Error("Cette fonctionnalite est maintenant dans le back-office Odoo (/web).");
  }
  const res = await fetch(API + mapped, {
    method: opts.method || "GET",
    headers: { "Content-Type": "application/json", ...opts.headers },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin"
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload.ok === false) throw new Error(payload.error || `Erreur ${res.status}`);
  // Unwrap the {"ok": true, "data": ...} envelope.
  let data = (payload && typeof payload === "object" && payload.ok === true && "data" in payload)
    ? payload.data
    : payload;
  // login / register / me nest the user one level deeper ({user, tokens?}).
  const path = String(url).split("?")[0];
  if (["/api/login", "/api/register", "/api/me"].includes(path)
      && data && typeof data === "object" && !Array.isArray(data) && data.user) {
    return data.user;
  }
  return data;
}

function $(sel) { return document.querySelector(sel); }
function html(str) { return String(str || "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function money(n) { return Number(n || 0).toLocaleString() + " XOF"; }

async function loadUser() {
  try { state.user = await api("/api/me"); } catch { state.user = null; }
  await renderNav();
  refreshNotifications();
}

async function cartCount() {
  try {
    const items = await api("/api/cart");
    return items.reduce((a, i) => a + i.quantity, 0);
  } catch (e) { return 0; }
}

function navLink(page, label) {
  return `<a href="#${page}" onclick="event.preventDefault(); go('${page}'); return false;">${label}</a>`;
}

async function renderNav() {
  const nav = $("#main-nav");
  if (!nav) return;
  const count = state.user && state.user.role === "client" ? await cartCount() : 0;
  let links = navLink("home", "Accueil");
  if (!state.user) {
    links += navLink("catalog", "Catalogue") + navLink("login", "Connexion") + navLink("register", "Inscription");
  } else {
    if (state.user.role === "client") {
      links += navLink("catalog", "Catalogue")
        + navLink("cart", `Panier${count ? ` <span class="badge">${count}</span>` : ""}`)
        + navLink("orders", "Commandes")
        + navLink("courier", "Course colis")
        + navLink("profile", "Profil");
    }
    if (state.user.role === "fournisseur") links += navLink("supplier", "Fournisseur") + navLink("profile", "Profil");
    if (state.user.role === "societe") links += navLink("societe", "Societe") + navLink("profile", "Profil");
    if (state.user.role === "livreur") links += navLink("livreur", "Livreur") + navLink("profile", "Profil");
    if (state.user.role === "admin") links += `<a href="/web">Admin</a>` + navLink("profile", "Profil");
    links += `<button type="button" class="notif-toggle" onclick="toggleNotifPanel()">🔔<span id="notif-badge" class="badge hidden">0</span></button>`;
    links += `<button type="button" onclick="logout()">Deconnecter</button>`;
  }
  nav.innerHTML = links;
}

function go(page, params) {
  let hash = page || "home";
  if (params) {
    const q = new URLSearchParams();
    for (const k in params) {
      if (params[k] !== undefined && params[k] !== null) q.set(k, params[k]);
    }
    const qs = q.toString();
    if (qs) hash += "?" + qs;
  }
  const current = (window.location.hash || "").replace(/^#/, "");
  // Always set hash for deep-linking; only force-render when hash already matches
  // (hashchange would not fire). Rely on hashchange for the normal path to avoid
  // double-render races with <a href="#"> style links.
  if (current === hash) {
    render(page || "home", params || {});
  } else {
    window.location.hash = hash;
  }
}

function parseHash() {
  const raw = (window.location.hash || "").replace(/^#/, "").replace(/^\/+/, "");
  const [page, query] = raw.split("?");
  const params = {};
  if (query) new URLSearchParams(query).forEach((v, k) => params[k] = v);
  return { page: (page || "home").replace(/^\/+/, "") || "home", params };
}

function render(page, params) {
  const app = $("#app");
  if (!app) return;
  switch(page || "home") {
    case "home": return renderHome(app);
    case "catalog": return renderCatalog(app, params);
    case "cart": return renderCart(app);
    case "checkout": return renderCheckout(app, params);
    case "login": return renderLogin(app);
    case "register": return renderRegister(app);
    case "orders": return renderOrders(app);
    case "order": return renderOrderDetail(app, params);
    case "courier": return renderCourier(app);
    case "supplier": return renderSupplier(app);
    case "societe": return renderSociete(app);
    case "livreur": return renderLivreur(app);
    case "admin": return renderAdmin(app);
    case "payment": return renderPayment(app, params);
    case "profile": return renderProfile(app);
    default: renderHome(app);
  }
}

async function renderHome(app) {
  app.innerHTML = `
    <div class="card">
      <h1>🚚 Livraison Express</h1>
      <p>Plateforme de gestion de courses et de livraisons. Commandez des produits pres de chez vous ou demandez une course colis.</p>
      <div id="install-banner"></div>
      <div class="grid grid-2">
        <div class="card">
          <h3>Client</h3>
          <p>Parcourez le catalogue, passez commande, suivez votre livraison et payez en toute securite.</p>
          <div id="home-categories" style="margin-bottom:0.75rem;">Chargement...</div>
          <button class="btn" onclick="go('catalog')">Voir tout le catalogue</button>
          <button class="btn secondary" onclick="go('courier')">Demander une course</button>
        </div>
        <div class="card">
          <h3>Fournisseur / Livreur / Admin</h3>
          <p>Connectez-vous pour gerer vos commandes, missions ou validations.</p>
          <button class="btn" onclick="go('login')">Connexion</button>
          <button class="btn secondary" onclick="go('register')">Creer un compte</button>
        </div>
      </div>
    </div>`;
  showInstallBanner();
  try {
    const cats = await api("/api/categories");
    const grid = cats.map(c => `
      <button class="btn secondary" style="justify-content:flex-start;gap:0.5rem;"
              onclick="go('catalog', {cat:${c.id}})">${html(c.icon || '')} ${html(c.name)}</button>
    `).join("");
    $("#home-categories").innerHTML = `
      <p style="font-weight:600;margin-bottom:0.5rem;">Choisir une categorie :</p>
      <div class="grid grid-2" style="gap:0.5rem;">${grid}</div>`;
  } catch (e) {
    $("#home-categories").innerHTML = `<p class="error">${e.message}</p>`;
  }
}

function showInstallBanner() {
  const box = $("#install-banner");
  if (!box || !state.installPrompt) return;
  box.innerHTML = `<div class="install-banner">
    <span>Installer Livraison Express sur votre telephone ?</span>
    <button class="btn small" onclick="installApp()">Installer</button>
  </div>`;
}

window.addEventListener("beforeinstallprompt", e => {
  e.preventDefault();
  state.installPrompt = e;
  showInstallBanner();
});

function installApp() {
  if (state.installPrompt) {
    state.installPrompt.prompt();
    state.installPrompt = null;
    $("#install-banner").innerHTML = "";
  }
}

async function renderCatalog(app, params) {
  app.innerHTML = `<div class="card"><h2>Catalogue</h2>
    <div id="filters" style="margin-bottom:1rem;"></div>
    <div id="products" class="grid grid-3">Chargement...</div>
  </div>`;
  if (!state.categories.length) state.categories = await api("/api/categories");
  if (!state.suppliers.length) state.suppliers = await api("/api/suppliers");
  // Always reload products so new supplier images appear
  state.products = await api("/api/products");
  const catSel = `<select id="catFilter" onchange="filterCatalog()"><option value="">Toutes categories</option>${state.categories.map(c => `<option value="${c.id}">${html(c.icon + " " + c.name)}</option>`).join("")}</select>`;
  const supSel = `<select id="supFilter" onchange="filterCatalog()"><option value="">Tous fournisseurs</option>${state.suppliers.map(s => `<option value="${s.id}">${html(s.company_name)}${s.open_now === false ? " (Ferme)" : s.open_now ? " (Ouvert)" : ""}</option>`).join("")}</select>`;
  const searchBar = `
    <div class="catalog-search">
      <input id="catalogSearch" type="search" placeholder="Rechercher un plat ou un fournisseur (nom d'entreprise)..."
        aria-label="Rechercher un plat ou un fournisseur" oninput="filterCatalog()" autocomplete="off">
    </div>`;
  $("#filters").innerHTML = `${searchBar}<div class="grid grid-2" style="margin-top:0.75rem;">${catSel}${supSel}</div>`;
  if (params && params.cat) {
    const cf = $("#catFilter");
    if (cf) cf.value = params.cat;
  }
  if (params && params.q) {
    const sf = $("#catalogSearch");
    if (sf) sf.value = params.q;
  }
  filterCatalog();
}

function filterCatalog() {
  const cat = $("#catFilter") ? $("#catFilter").value : "";
  const sup = $("#supFilter") ? $("#supFilter").value : "";
  const q = ($("#catalogSearch") ? $("#catalogSearch").value : "").trim().toLowerCase();
  const filtered = state.products.filter(p => {
    if (cat && p.category_id != cat) return false;
    if (sup && p.supplier_id != sup) return false;
    if (q) {
      const hay = [
        p.name,
        p.description,
        p.supplier_name,
        p.supplier_company,
        p.category_name
      ].map(x => (x || "").toLowerCase()).join(" ");
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const placeholder = productPlaceholder(160);
  $("#products").innerHTML = filtered.map(p => {
    const imgSrc = p.image_url
      ? (p.image_url.startsWith("http") ? p.image_url : `${p.image_url}${p.image_url.includes("?") ? "&" : "?"}v=${encodeURIComponent(p.updated_at || p.id)}`)
      : placeholder;
    const company = (p.supplier_company || p.supplier_name || "Fournisseur").trim();
    const openBadge = p.supplier_open_now
      ? `<span class="badge-open">Ouvert</span>`
      : `<span class="badge-closed">Ferme</span>`;
    return `
    <div class="card product">
      <button type="button" class="product-img-btn" onclick="openProductDetail(${p.id})" title="Voir le detail du produit" aria-label="Voir detail ${html(p.name)}">
        <img class="product-img" src="${html(imgSrc)}" alt="${html(p.name)}" loading="lazy">
      </button>
      <div><strong>${html(p.name)}</strong> <span class="tag">${html(p.category_name)}</span>${p.fragile ? ' <span class="tag" style="background:#fee2e2;color:var(--danger);">Fragile</span>' : ''}</div>
      <div class="price">${money(p.price)}${p.stock <= 5 ? ` <span class="tag">Stock: ${p.stock}</span>` : ''}</div>
      <div style="display:flex;gap:0.5rem;margin-top:auto;flex-wrap:wrap;">
        <button type="button" class="btn" onclick="addToCart(${p.id})" ${p.supplier_open_now === false ? "disabled title=\"Boutique fermee\"" : ""}>Ajouter</button>
        <button type="button" class="btn secondary" onclick="go('cart')">Panier</button>
      </div>
      <div class="product-company" title="Nom de la societe">
        <span>${html(company)}</span> ${openBadge}
      </div>
    </div>
  `;
  }).join("") || `<p>Aucun produit${q ? " pour « " + html(q) + " »" : ""}.</p>`;
}

function productPlaceholder(h) {
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='400' height='${h}'%3E%3Crect width='100%25' height='100%25' fill='%23eef2f7'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dominant-baseline='middle' fill='%2394a3b8' font-size='16'%3EProduit%3C/text%3E%3C/svg%3E`;
}

async function openProductDetail(pid) {
  try {
    openModal(`<div style="text-align:center;padding:1rem;">Chargement du produit...</div>`);
    let p = (state.products || []).find(x => x.id === pid);
    try {
      p = await api(`/api/products/${pid}`);
    } catch (e) {
      if (!p) throw e;
    }
    const img = p.image_url || productPlaceholder(280);
    const stockLabel = p.stock > 5
      ? `<span class="tag" style="background:#d1fae5;color:var(--ok);">En stock (${p.stock})</span>`
      : (p.stock > 0
        ? `<span class="tag" style="background:#fef3c7;color:var(--warn);">Stock faible (${p.stock})</span>`
        : `<span class="tag" style="background:#fee2e2;color:var(--danger);">Rupture</span>`);

    openModal(`
      <div class="product-detail">
        <div class="product-detail-header">
          <h2 style="margin:0;flex:1;">${html(p.name)}</h2>
          <button type="button" class="btn small secondary" onclick="closeModal()" aria-label="Fermer">✕</button>
        </div>
        <div class="product-detail-body">
          <img class="product-detail-img" src="${html(img)}" alt="${html(p.name)}">
          <div class="product-detail-info">
            <div class="price" style="font-size:1.35rem;">${money(p.price)}</div>
            <div style="display:flex;flex-wrap:wrap;gap:0.35rem;margin:0.5rem 0;">
              <span class="tag">${html(p.category_name || "Sans categorie")}</span>
              ${p.fragile ? `<span class="tag" style="background:#fee2e2;color:var(--danger);">Fragile</span>` : ""}
              ${stockLabel}
            </div>
            <p style="color:var(--muted);margin:0.75rem 0;">
              ${html(p.description || "Aucune description disponible pour ce produit.")}
            </p>
            <div class="card" style="background:#f8fafc;margin:0.75rem 0;padding:0.75rem;">
              <strong>Société / Fournisseur</strong>
              <div style="font-weight:600;display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                ${html(p.supplier_company || p.supplier_name || "—")}
                ${p.supplier_open_now
                  ? `<span class="badge-open">Ouvert</span>`
                  : `<span class="badge-closed">Ferme</span>`}
              </div>
              ${p.supplier_phone ? `<div><a href="tel:${html(p.supplier_phone)}">${html(p.supplier_phone)}</a></div>` : ""}
              ${p.supplier_address ? `<div style="font-size:0.9rem;color:var(--muted);">${html(p.supplier_address)}</div>` : ""}
            </div>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:1rem;">
              <button type="button" class="btn" ${p.stock <= 0 ? "disabled" : ""} onclick="addToCartFromDetail(${p.id})">
                🛒 Ajouter au panier
              </button>
              <button type="button" class="btn secondary" onclick="closeModal()">Fermer</button>
            </div>
          </div>
        </div>
      </div>
    `);
  } catch (e) {
    openModal(`
      <div>
        <h2>Produit</h2>
        <p class="error">${html(e.message)}</p>
        <button type="button" class="btn secondary" onclick="closeModal()">Fermer</button>
      </div>
    `);
  }
}

async function addToCartFromDetail(pid) {
  try {
    await addToCart(pid, { stayOnPage: true, closeDetail: true });
  } catch (e) {
    alert(e.message);
  }
}

/**
 * Gate: if not logged in as client, offer Login OR Create client account,
 * then resume the pending action (add to cart / checkout / cart).
 */
function requireClientAuth(action) {
  if (state.user && state.user.role === "client") return true;
  if (state.user && state.user.role !== "client") {
    alert("Connectez-vous avec un compte Client pour continuer vos achats.");
    return false;
  }
  pendingClientAction = action || null;
  openClientAuthGate();
  return false;
}

function openClientAuthGate(tab) {
  tab = tab || "choice";
  const productHint = pendingClientAction && pendingClientAction.type === "addToCart"
    ? "<p style=\"color:var(--muted);font-size:0.9rem;\">Pour ajouter ce produit et continuer, connectez-vous ou creez un compte <strong>Client</strong>.</p>"
    : "<p style=\"color:var(--muted);font-size:0.9rem;\">Pour continuer votre parcours d'achat, connectez-vous ou creez un compte <strong>Client</strong>.</p>";

  if (tab === "choice") {
    openModal(`
      <div class="auth-gate">
        <div class="product-detail-header">
          <h2 style="margin:0;flex:1;">Continuer vos achats</h2>
          <button type="button" class="btn small secondary" onclick="closeModal(); pendingClientAction=null;" aria-label="Fermer">✕</button>
        </div>
        ${productHint}
        <div class="grid grid-2" style="gap:0.75rem;margin-top:1rem;">
          <button type="button" class="btn" style="padding:1rem;" onclick="openClientAuthGate('login')">
            J'ai deja un compte<br><small style="opacity:0.85;font-weight:500;">Se connecter</small>
          </button>
          <button type="button" class="btn secondary" style="padding:1rem;" onclick="openClientAuthGate('register')">
            Creer un compte client<br><small style="opacity:0.85;font-weight:500;">Inscription rapide</small>
          </button>
        </div>
        <p style="font-size:0.8rem;color:var(--muted);margin-top:1rem;">Demo client : +22800000004 / cli123</p>
      </div>
    `);
    return;
  }

  if (tab === "login") {
    openModal(`
      <div class="auth-gate">
        <div class="product-detail-header">
          <h2 style="margin:0;flex:1;">Connexion client</h2>
          <button type="button" class="btn small secondary" onclick="closeModal(); pendingClientAction=null;">✕</button>
        </div>
        <p style="color:var(--muted);font-size:0.9rem;">Connectez-vous pour continuer.</p>
        <label>Telephone</label>
        <input id="gatePhone" placeholder="+228..." value="+22800000004">
        <label>Mot de passe</label>
        <input id="gatePassword" type="password" value="cli123">
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:1rem;">
          <button type="button" class="btn" onclick="doClientGateLogin()">Se connecter</button>
          <button type="button" class="btn secondary" onclick="openClientAuthGate('choice')">Retour</button>
        </div>
        <p style="margin-top:0.75rem;font-size:0.85rem;">
          Pas encore de compte ?
          <a href="#" onclick="event.preventDefault(); openClientAuthGate('register');">Creer un compte client</a>
        </p>
        <div id="gateMsg"></div>
      </div>
    `);
    return;
  }

  // register (client only)
  openModal(`
    <div class="auth-gate">
      <div class="product-detail-header">
        <h2 style="margin:0;flex:1;">Creer un compte client</h2>
        <button type="button" class="btn small secondary" onclick="closeModal(); pendingClientAction=null;">✕</button>
      </div>
      <p style="color:var(--muted);font-size:0.9rem;">Inscription rapide pour commander et suivre vos livraisons.</p>
      <div class="form-row">
        <div><label>Prenom</label><input id="gateFirst" placeholder="Ama"></div>
        <div><label>Nom</label><input id="gateLast" placeholder="Client"></div>
      </div>
      <label>Telephone</label>
      <input id="gatePhone" placeholder="+228 XX XX XX XX" required>
      <label>Mot de passe</label>
      <input id="gatePassword" type="password" placeholder="••••••••" required>
      <label>Adresse (optionnel)</label>
      <input id="gateAddress" placeholder="Quartier, ville">
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:1rem;">
        <button type="button" class="btn" onclick="doClientGateRegister()">Creer et continuer</button>
        <button type="button" class="btn secondary" onclick="openClientAuthGate('choice')">Retour</button>
      </div>
      <p style="margin-top:0.75rem;font-size:0.85rem;">
        Deja un compte ?
        <a href="#" onclick="event.preventDefault(); openClientAuthGate('login');">Se connecter</a>
      </p>
      <div id="gateMsg"></div>
    </div>
  `);
}

async function doClientGateLogin() {
  const msg = $("#gateMsg");
  try {
    const phone = ($("#gatePhone") && $("#gatePhone").value || "").trim();
    const password = ($("#gatePassword") && $("#gatePassword").value) || "";
    if (!phone || !password) {
      if (msg) msg.innerHTML = `<p class="error">Telephone et mot de passe requis.</p>`;
      return;
    }
    state.user = await api("/api/login", { method: "POST", body: { phone, password } });
    if (state.user.role !== "client") {
      await api("/api/logout", { method: "POST" });
      state.user = null;
      if (msg) msg.innerHTML = `<p class="error">Ce compte n'est pas un compte Client. Utilisez un compte client ou creez-en un.</p>`;
      return;
    }
    await renderNav();
    if (msg) msg.innerHTML = `<p class="success">Connecte. Continuation...</p>`;
    await resumePendingClientAction();
  } catch (e) {
    if (msg) msg.innerHTML = `<p class="error">${html(e.message)}</p>`;
  }
}

async function doClientGateRegister() {
  const msg = $("#gateMsg");
  try {
    const phone = ($("#gatePhone") && $("#gatePhone").value || "").trim();
    const password = ($("#gatePassword") && $("#gatePassword").value) || "";
    const first_name = ($("#gateFirst") && $("#gateFirst").value || "").trim();
    const last_name = ($("#gateLast") && $("#gateLast").value || "").trim();
    const address = ($("#gateAddress") && $("#gateAddress").value || "").trim();
    if (!phone || !password) {
      if (msg) msg.innerHTML = `<p class="error">Telephone et mot de passe requis.</p>`;
      return;
    }
    if (password.length < 4) {
      if (msg) msg.innerHTML = `<p class="error">Mot de passe trop court (min. 4 caracteres).</p>`;
      return;
    }
    await api("/api/register", {
      method: "POST",
      body: {
        phone, password, role: "client",
        first_name, last_name, address,
        company_name: null
      }
    });
    state.user = await api("/api/login", { method: "POST", body: { phone, password } });
    await renderNav();
    if (msg) msg.innerHTML = `<p class="success">Compte client cree. Continuation...</p>`;
    await resumePendingClientAction();
  } catch (e) {
    if (msg) msg.innerHTML = `<p class="error">${html(e.message)}</p>`;
  }
}

async function resumePendingClientAction() {
  const action = pendingClientAction;
  pendingClientAction = null;
  closeModal();
  if (!action) {
    go("catalog");
    return;
  }
  if (action.type === "addToCart") {
    await addToCart(action.productId, action.opts || { stayOnPage: false });
    return;
  }
  if (action.type === "go") {
    go(action.page, action.params);
    return;
  }
  go("cart");
}

async function addToCart(pid, opts) {
  opts = opts || {};
  if (!requireClientAuth({ type: "addToCart", productId: pid, opts })) return;
  try {
    await api("/api/cart", { method: "POST", body: { product_id: pid, quantity: 1 } });
    await renderNav();
    if (opts.closeDetail) closeModal();
    if (opts.stayOnPage) {
      alert("Produit ajoute au panier.");
      return;
    }
    // Open cart so content is visible immediately after add
    go("cart");
  } catch (e) {
    alert(e.message);
  }
}

function setCartContent(htmlStr) {
  const box = $("#cart-content");
  if (box) box.innerHTML = htmlStr;
}

async function renderCart(app) {
  if (!app) app = $("#app");
  if (!app) return;
  if (!state.user || state.user.role !== "client") {
    app.innerHTML = `<div class="card"><h2>Mon panier</h2>
      <p>Pour voir votre panier et commander, connectez-vous ou creez un compte client.</p>
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
        <button class="btn" type="button" onclick="pendingClientAction={type:'go',page:'cart'}; openClientAuthGate('choice');">Continuer</button>
        <button class="btn secondary" type="button" onclick="go('catalog')">Catalogue</button>
      </div>
    </div>`;
    return;
  }
  app.innerHTML = `<div class="card"><h2>Mon panier multi-fournisseurs</h2><div id="cart-content">Chargement...</div></div>`;
  try {
    const items = await api("/api/cart");
    // Ignore stale responses if user navigated away
    if (!$("#cart-content")) return;
    if (!Array.isArray(items) || !items.length) {
      setCartContent(`<p>Panier vide.</p><button class="btn" type="button" onclick="go('catalog')">Parcourir le catalogue</button>`);
      await renderNav();
      return;
    }
    const bySupplier = {};
    items.forEach(item => {
      const sid = item.supplier_id;
      if (!bySupplier[sid]) bySupplier[sid] = { name: item.supplier_name || "Fournisseur", items: [] };
      bySupplier[sid].items.push(item);
    });

    setCartContent(Object.entries(bySupplier).map(([sid, group]) => {
      const subtotal = group.items.reduce((a, i) => a + Number(i.unit_price || 0) * Number(i.quantity || 0), 0);
      return `
        <div class="card" style="margin-bottom:1rem;">
          <h3>${html(group.name)} <span class="tag">${group.items.length} article(s)</span></h3>
          ${group.items.map(i => `
            <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border);padding:0.5rem 0;gap:0.5rem;flex-wrap:wrap;">
              <div style="display:flex;align-items:center;gap:0.75rem;">
                <img src="${html(i.image_url || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2240%22 height=%2240%22%3E%3Crect width=%22100%25%22 height=%22100%25%22 fill=%22%23eef2f7%22/%3E%3C/svg%3E')}" alt="" style="width:40px;height:40px;object-fit:cover;border-radius:4px;">
                <div><strong>${html(i.product_name)}</strong><br>${money(i.unit_price)} × ${i.quantity}</div>
              </div>
              <div style="display:flex;align-items:center;gap:0.5rem;">
                <button type="button" class="btn small secondary" onclick="updateCartItem(${i.id}, ${i.quantity - 1})">−</button>
                <span>${i.quantity}</span>
                <button type="button" class="btn small secondary" onclick="updateCartItem(${i.id}, ${i.quantity + 1})">+</button>
                <button type="button" class="btn small danger" onclick="removeCartItem(${i.id})">×</button>
              </div>
            </div>
          `).join("")}
          <div class="price" style="margin-top:0.5rem;">Sous-total: ${money(subtotal)}</div>
        </div>
      `;
    }).join("") + `
      <div class="card">
        <div class="price">Total general: ${money(items.reduce((a, i) => a + Number(i.unit_price || 0) * Number(i.quantity || 0), 0))}</div>
        <div style="margin-top:1rem;display:flex;gap:0.5rem;flex-wrap:wrap;">
          <button type="button" class="btn" onclick="go('catalog')">Continuer achats</button>
          <button type="button" class="btn" onclick="go('checkout')">Passer toutes les commandes</button>
          <button type="button" class="btn secondary" onclick="clearCart()">Vider le panier</button>
        </div>
      </div>
    `);
    await renderNav();
  } catch (e) {
    setCartContent(`<p class="error">${html(e.message)}</p>`);
  }
}

async function updateCartItem(itemId, newQty) {
  try {
    if (newQty <= 0) {
      await removeCartItem(itemId);
      return;
    }
    const item = (await api("/api/cart")).find(i => i.id === itemId);
    if (!item) return;
    await api("/api/cart", { method: "POST", body: { product_id: item.product_id, quantity: newQty - item.quantity } });
    await renderCart($("#app"));
    await renderNav();
  } catch (e) { alert(e.message); }
}

async function removeCartItem(itemId) {
  try {
    await api(`/api/cart?item_id=${itemId}`, { method: "DELETE" });
    await renderCart($("#app"));
    await renderNav();
  } catch (e) { alert(e.message); }
}

async function clearCart() {
  if (!confirm("Vider le panier ?")) return;
  try {
    await api("/api/cart", { method: "DELETE" });
    await renderCart($("#app"));
    await renderNav();
  } catch (e) { alert(e.message); }
}

async function renderCheckout(app, params) {
  if (!requireClientAuth({ type: "go", page: "checkout", params })) {
    app.innerHTML = `<div class="card"><h2>Finaliser la commande</h2>
      <p>Connectez-vous ou creez un compte client pour continuer.</p></div>`;
    return;
  }
  const defaultAddress = (state.user && state.user.address) || "Adidogome, Lome";
  const defaultPhone = state.user ? state.user.phone : "";
  app.innerHTML = `<div class="card">
      <h2>Finaliser la commande</h2>
      <p style="color:var(--muted);font-size:0.9rem;">Choisissez d'abord comment recevoir vos produits, puis le mode de paiement.</p>

      <h3 style="margin-top:1rem;">1. Reception</h3>
      <div class="grid grid-2" style="gap:0.75rem;margin-bottom:1rem;">
        <label class="card" style="cursor:pointer;margin:0;border:2px solid var(--primary);">
          <input type="radio" name="mode" value="delivery" checked onchange="onCheckoutOptionsChange()" style="margin-right:0.5rem;">
          <strong>🚚 Me faire livrer</strong>
          <div style="font-size:0.85rem;color:var(--muted);margin-top:0.25rem;">Livraison a domicile — frais de livraison appliques</div>
        </label>
        <label class="card" style="cursor:pointer;margin:0;">
          <input type="radio" name="mode" value="pickup" onchange="onCheckoutOptionsChange()" style="margin-right:0.5rem;">
          <strong>🏪 Recuperer moi-meme</strong>
          <div style="font-size:0.85rem;color:var(--muted);margin-top:0.25rem;">Retrait chez le fournisseur — pas de frais de livraison</div>
        </label>
      </div>

      <div id="addressBlock">
        <label>Adresse de livraison (lieu de remise)</label>
        <input id="address" placeholder="Rue, quartier, ville" value="${html(defaultAddress)}">
      </div>

      <label>Telephone du destinataire (pour que le livreur puisse appeler a l'arrivee)</label>
      <input id="guestPhone" placeholder="+228 XX XX XX XX" value="${html(defaultPhone)}" required>

      <div id="societeBlock">
        <h3 style="margin-top:1rem;">Societe de livraison</h3>
        <p style="font-size:0.85rem;color:var(--muted);margin:0 0 0.5rem;">
          Choisissez une societe a l'avance, ou laissez la plateforme / les livreurs boutique.
        </p>
        <select id="preferredSociete"><option value="">Chargement...</option></select>
      </div>

      <h3 style="margin-top:1rem;">2. Paiement</h3>
      <div id="paymentBlock"></div>

      <div id="summary" style="margin-top:1rem;">Chargement du recapitulatif...</div>
      <button class="btn" type="button" style="margin-top:1rem;" onclick="submitCheckout()">Confirmer la commande</button>
      <div id="msg"></div>
    </div>`;
  onCheckoutOptionsChange();
  loadCheckoutSocietes();
}

async function loadCheckoutSocietes() {
  const sel = $("#preferredSociete");
  if (!sel) return;
  const pref = state.user && state.user.preferred_societe_id ? String(state.user.preferred_societe_id) : "";
  try {
    const list = await api("/api/societes");
    sel.innerHTML = `<option value="">Aucune (boutique / plateforme)</option>` +
      (list || []).map(s =>
        `<option value="${s.id}" ${String(s.id) === pref ? "selected" : ""}>${html(s.company_name)}${s.fleet_count ? ` — ${s.fleet_count} livreur(s)` : ""}</option>`
      ).join("");
  } catch (e) {
    sel.innerHTML = `<option value="">Aucune (boutique / plateforme)</option>`;
  }
}

function getCheckoutMode() {
  const el = document.querySelector('input[name="mode"]:checked');
  return el ? el.value : "delivery";
}

function getCheckoutPayment() {
  const el = document.querySelector('input[name="payment"]:checked');
  return el ? el.value : "cash_on_delivery";
}

function onCheckoutOptionsChange() {
  const mode = getCheckoutMode();
  // highlight selected reception cards
  document.querySelectorAll('input[name="mode"]').forEach(r => {
    const card = r.closest("label");
    if (card) card.style.border = r.checked ? "2px solid var(--primary)" : "1px solid var(--border)";
  });
  const addressBlock = $("#addressBlock");
  if (addressBlock) addressBlock.className = mode === "pickup" ? "hidden" : "";
  const societeBlock = $("#societeBlock");
  if (societeBlock) societeBlock.className = mode === "pickup" ? "hidden" : "";

  const payBox = $("#paymentBlock");
  if (!payBox) return;
  if (mode === "delivery") {
    payBox.innerHTML = `
      <p style="font-size:0.85rem;color:var(--muted);margin-bottom:0.5rem;">
        Vous payez uniquement le <strong>prix des produits</strong> + les <strong>frais de livraison</strong> (sans majoration).
      </p>
      <label class="card" style="display:block;cursor:pointer;margin-bottom:0.5rem;border:2px solid var(--primary);">
        <input type="radio" name="payment" value="cash_on_delivery" checked onchange="refreshCheckoutPreview()" style="margin-right:0.5rem;">
        <strong>💵 Paiement a la livraison</strong>
        <div style="font-size:0.85rem;color:var(--muted);">Produits + frais de livraison a la reception</div>
      </label>
      <label class="card" style="display:block;cursor:pointer;margin-bottom:0.5rem;">
        <input type="radio" name="payment" value="tmoney" onchange="refreshCheckoutPreview()" style="margin-right:0.5rem;">
        <strong>Tmoney</strong> — payer maintenant (produits + livraison)
      </label>
      <label class="card" style="display:block;cursor:pointer;margin-bottom:0.5rem;">
        <input type="radio" name="payment" value="flooz" onchange="refreshCheckoutPreview()" style="margin-right:0.5rem;">
        <strong>Flooz</strong> — payer maintenant (produits + livraison)
      </label>
      <label class="card" style="display:block;cursor:pointer;margin-bottom:0.5rem;">
        <input type="radio" name="payment" value="ecobank" onchange="refreshCheckoutPreview()" style="margin-right:0.5rem;">
        <strong>Ecobank Express</strong> — payer maintenant (produits + livraison)
      </label>
    `;
  } else {
    payBox.innerHTML = `
      <p style="font-size:0.85rem;color:var(--muted);margin-bottom:0.5rem;">
        Retrait magasin : <strong>aucun frais de livraison</strong>. Payez les produits maintenant ou au retrait.
      </p>
      <label class="card" style="display:block;cursor:pointer;margin-bottom:0.5rem;border:2px solid var(--primary);">
        <input type="radio" name="payment" value="pay_at_pickup" checked onchange="refreshCheckoutPreview()" style="margin-right:0.5rem;">
        <strong>🏪 Payer au retrait</strong>
        <div style="font-size:0.85rem;color:var(--muted);">Reglez les produits chez le fournisseur</div>
      </label>
      <label class="card" style="display:block;cursor:pointer;margin-bottom:0.5rem;">
        <input type="radio" name="payment" value="tmoney" onchange="refreshCheckoutPreview()" style="margin-right:0.5rem;">
        <strong>Tmoney</strong> — payer les produits maintenant
      </label>
      <label class="card" style="display:block;cursor:pointer;margin-bottom:0.5rem;">
        <input type="radio" name="payment" value="flooz" onchange="refreshCheckoutPreview()" style="margin-right:0.5rem;">
        <strong>Flooz</strong> — payer les produits maintenant
      </label>
      <label class="card" style="display:block;cursor:pointer;margin-bottom:0.5rem;">
        <input type="radio" name="payment" value="ecobank" onchange="refreshCheckoutPreview()" style="margin-right:0.5rem;">
        <strong>Ecobank Express</strong> — payer les produits maintenant
      </label>
    `;
  }
  document.querySelectorAll('input[name="payment"]').forEach(r => {
    r.addEventListener("change", () => {
      document.querySelectorAll('input[name="payment"]').forEach(x => {
        const card = x.closest("label");
        if (card) card.style.border = x.checked ? "2px solid var(--primary)" : "1px solid var(--border)";
      });
    });
  });
  refreshCheckoutPreview();
}

async function refreshCheckoutPreview() {
  const box = $("#summary");
  if (!box) return;
  box.innerHTML = "Calcul du recapitulatif...";
  try {
    const mode = getCheckoutMode();
    const payment = getCheckoutPayment();
    const preview = await api("/api/cart/checkout-preview", {
      method: "POST",
      body: {
        mode,
        payment_method: payment,
        delivery_lat: 6.16,
        delivery_lon: 1.21,
      }
    });
    const groupsHtml = (preview.groups || []).map(g => `
      <div class="card" style="margin-bottom:0.75rem;${g.available ? "" : "opacity:0.7;border-color:var(--danger);"}">
        <strong>${html(g.supplier_name)}</strong>
        ${g.available ? "" : `<p class="error">${html(g.reason || "Indisponible")}</p>`}
        ${(g.lines || []).map(l => `<div>${html(l.name)} × ${l.quantity} = ${money(l.line_total)}</div>`).join("")}
        <div style="margin-top:0.35rem;font-size:0.9rem;">
          Produits: <strong>${money(g.product_total)}</strong>
          ${mode === "delivery" ? `
            <br>Frais livraison: <strong>${money(g.delivery_fee)}</strong>
          ` : `<br><span class="tag">Retrait — 0 frais livraison</span>`}
          <br>Sous-total: <strong class="price">${money(g.subtotal)}</strong>
        </div>
      </div>
    `).join("");

    let dueHtml = "";
    if (mode === "delivery" && payment === "cash_on_delivery") {
      dueHtml = `
        <p class="price">A payer a la livraison: ${money(preview.amount_due_on_delivery)}</p>
        <p style="font-size:0.85rem;color:var(--muted);">Produits ${money(preview.products_total)} + livraison ${money(preview.delivery_total)}</p>
        <p style="font-size:0.85rem;">A payer maintenant: <strong>${money(0)}</strong></p>`;
    } else if (mode === "pickup" && payment === "pay_at_pickup") {
      dueHtml = `
        <p class="price">A payer au retrait: ${money(preview.products_total)}</p>
        <p style="font-size:0.85rem;">A payer maintenant: <strong>${money(0)}</strong></p>`;
    } else {
      dueHtml = `
        <p class="price">A payer maintenant: ${money(preview.grand_total)}</p>
        <p style="font-size:0.85rem;color:var(--muted);">Produits ${money(preview.products_total)}${mode === "delivery" ? ` + livraison ${money(preview.delivery_total)}` : ""}</p>`;
    }

    box.innerHTML = `
      <h3>3. Recapitulatif</h3>
      ${groupsHtml || "<p>Panier vide.</p>"}
      <div class="card" style="background:#f8fafc;">
        <div>Prix des produits: <strong>${money(preview.products_total)}</strong></div>
        <div>Frais de livraison: <strong>${money(preview.delivery_total)}</strong></div>
        <div class="price" style="margin-top:0.35rem;">Total = produits + livraison: ${money(preview.grand_total)}</div>
        <hr style="border:none;border-top:1px solid var(--border);margin:0.75rem 0;">
        ${dueHtml}
      </div>
    `;
  } catch (e) {
    box.innerHTML = `<p class="error">${html(e.message)}</p>`;
  }
}

function toggleAddress() {
  onCheckoutOptionsChange();
}

async function submitCheckout() {
  const mode = getCheckoutMode();
  const paymentMethod = getCheckoutPayment();
  const address = ($("#address") && $("#address").value || "").trim();
  const contactPhone = (($("#guestPhone") && $("#guestPhone").value) || (state.user ? state.user.phone : "") || "").trim();
  if (mode === "delivery" && !address) {
    $("#msg").innerHTML = `<p class="error">Indiquez l'adresse de livraison.</p>`;
    return;
  }
  if (!contactPhone) {
    $("#msg").innerHTML = `<p class="error">Indiquez le telephone du destinataire (pour que le livreur puisse appeler a l'arrivee).</p>`;
    return;
  }
  const societeSel = $("#preferredSociete");
  const preferredSocieteId = (mode === "delivery" && societeSel && societeSel.value)
    ? parseInt(societeSel.value, 10)
    : null;
  const body = {
    mode,
    delivery_address: mode === "delivery" ? address : null,
    delivery_lat: 6.16,
    delivery_lon: 1.21,
    payment_method: paymentMethod,
    payment_phone: contactPhone,
    guest_phone: contactPhone,
    preferred_societe_id: preferredSocieteId || null
  };
  try {
    const res = await api("/api/orders/multi", { method: "POST", body });
    if (!res.count) {
      const detail = (res.skipped && res.skipped.length) ? res.skipped.join(" — ") : "Verifiez horaires et validation admin du fournisseur.";
      $("#msg").innerHTML = `<p class="error">Aucune commande creee. ${html(detail)}</p>`;
      return;
    }
    let extra = "";
    if (res.skipped && res.skipped.length) {
      extra = `<p class="error" style="margin-top:0.5rem;">Non traitees : ${html(res.skipped.join(" — "))}</p>`;
    }
    const modeLabel = res.mode === "pickup" ? "Retrait" : "Livraison";
    $("#msg").innerHTML = `
      <p class="success">${res.count} commande(s) creee(s) — ${modeLabel} / ${html(res.payment_method)}</p>
      <ul>${res.orders.map(o => `
        <li>
          <strong>${o.code}</strong> — ${html(o.supplier)} — ${money(o.total)}
          <br><small>Produits ${money(o.product_total)}
          ${o.mode === "delivery" ? ` + livraison ${money(o.delivery_fee)}` : " (retrait, 0 livraison)"}
          — ${o.payment_status === "paid" ? "Paye" : (o.payment_method === "pay_at_pickup" ? "A payer au retrait" : "A payer a la livraison")}</small>
        </li>`).join("")}</ul>
      ${extra}
      <button class="btn secondary" type="button" onclick="go('orders')">Voir mes commandes</button>`;
    renderNav();
  } catch (e) {
    $("#msg").innerHTML = `<p class="error">${html(e.message)}</p>`;
  }
}

function renderLogin(app) {
  app.innerHTML = `
    <div class="card" style="max-width:420px;margin:auto;">
      <h2>Connexion</h2>
      <label>Telephone</label><input id="phone" value="+22800000004">
      <label>Mot de passe</label><input id="password" type="password" value="cli123">
      <button class="btn" onclick="doLogin()">Se connecter</button>
      <p style="margin-top:0.75rem;">Pas encore de compte client ?
        <a href="#register" onclick="event.preventDefault(); go('register');">Creer un compte</a>
      </p>
      <p style="font-size:0.85rem;color:var(--muted);">Demo : client +22800000004/cli123 — admin +22800000001/admin123 — fournisseur +22800000002/fou123 — livreur +22800000003/liv123</p>
      <div id="msg"></div>
    </div>`;
}

async function doLogin() {
  try {
    state.user = await api("/api/login", { method: "POST", body: { phone: $("#phone").value, password: $("#password").value } });
    renderNav();
    if (state.user.role === "admin") {
      // Administration is now the Odoo back-office.
      window.location.href = "/web";
      return;
    }
    if (pendingClientAction) {
      await resumePendingClientAction();
      return;
    }
    const dest = state.user.role === "admin" ? "admin"
      : state.user.role === "fournisseur" ? "supplier"
      : state.user.role === "societe" ? "societe"
      : state.user.role === "livreur" ? "livreur"
      : "catalog";
    go(dest);
  } catch (e) { $("#msg").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function logout() {
  await api("/api/logout", { method: "POST" });
  state.user = null;
  renderNav();
  go("home");
}

function renderRegister(app) {
  app.innerHTML = `
    <div class="card" style="max-width:520px;margin:auto;">
      <h2>Creer un compte</h2>
      <div class="form-row">
        <div><label>Telephone</label><input id="rphone"></div>
        <div><label>Mot de passe</label><input id="rpassword" type="password"></div>
      </div>
      <label>Type de compte</label>
      <select id="rrole" onchange="toggleRegisterExtra()">
        <option value="client" selected>Client (commander)</option>
        <option value="fournisseur">Fournisseur</option>
        <option value="livreur">Livreur</option>
        <option value="societe">Societe de livraison</option>
      </select>
      <div class="form-row">
        <div><label>Prenom</label><input id="rfirst"></div>
        <div><label>Nom</label><input id="rlast"></div>
      </div>
      <div id="regCompanyBlock" class="hidden">
        <label>Nom de la société</label>
        <input id="rcompany" placeholder="Ex. Restaurant Le Palmier" maxlength="120">
        <p style="font-size:0.85rem;color:var(--muted);margin:0.35rem 0 0;">Visible sous vos plats dans le catalogue.</p>
      </div>
      <label>Adresse</label><input id="raddress">
      <button class="btn" onclick="doRegister()">Creer mon compte</button>
      <p style="margin-top:0.75rem;">Deja un compte ?
        <a href="#login" onclick="event.preventDefault(); go('login');">Se connecter</a>
      </p>
      <div id="msg"></div>
    </div>`;
  toggleRegisterExtra();
}

function toggleRegisterExtra() {
  const block = $("#regCompanyBlock");
  const role = $("#rrole") ? $("#rrole").value : "client";
  if (block) block.className = (role === "fournisseur" || role === "societe") ? "" : "hidden";
}

async function doRegister() {
  const phone = $("#rphone").value;
  const password = $("#rpassword").value;
  try {
    await api("/api/register", { method: "POST", body: {
      phone: phone, password: password, role: $("#rrole").value,
      first_name: $("#rfirst").value, last_name: $("#rlast").value, company_name: $("#rcompany") ? $("#rcompany").value : null,
      address: $("#raddress").value
    }});
    // Connexion automatique apres inscription
    state.user = await api("/api/login", { method: "POST", body: { phone: phone, password: password } });
    renderNav();
    $("#msg").innerHTML = `<p class="success">Compte cree et connecte. Continuation...</p>`;
    if (pendingClientAction) {
      await resumePendingClientAction();
      return;
    }
    const dest = state.user.role === "client" ? "catalog"
      : state.user.role === "fournisseur" ? "supplier"
      : state.user.role === "societe" ? "societe"
      : state.user.role === "livreur" ? "livreur"
      : "home";
    setTimeout(() => go(dest), 600);
  } catch (e) { $("#msg").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function renderOrders(app) {
  app.innerHTML = `<div class="card"><h2>Mes commandes</h2><div id="list">Chargement...</div></div>`;
  const orders = await api("/api/orders");
  $("#list").innerHTML = orders.map(o => `
    <div class="card" style="display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap;">
      <div>
        <strong>${o.code}</strong> — ${html(o.supplier_name)}<br>
        <span class="status ${o.status}">${o.status}</span> ${o.mode} — ${money(o.total)}
      </div>
      <div style="display:flex;gap:0.5rem;">
        <button class="btn small" onclick="go('order', {id:${o.id}})">Voir</button>
        ${o.payment_status !== 'paid' && o.status !== 'CANCELLED' ? `<button class="btn small secondary" onclick="go('payment', {type:'order', id:${o.id}, amount:${o.total}})">Payer</button>` : ''}
      </div>
    </div>
  `).join("") || "<p>Aucune commande.</p>";
}

async function renderOrderDetail(app, params) {
  const id = params && params.id ? parseInt(params.id) : 0;
  app.innerHTML = `<div class="card"><h2>Commande</h2><div id="detail">Chargement...</div></div>`;
  const o = await api(`/api/orders/${id}`);
  let ratingHtml = "";
  if (state.user && state.user.role === "client" && o.status === "DELIVERED" && !o.rating) {
    const deliveredRun = (o.delivery_runs || []).find(r => r.status === "DELIVERED");
    ratingHtml = `<div class="card"><h3>Noter le livreur (1 a 5 ★)</h3>
      <p style="font-size:0.85rem;color:var(--muted);">Cette note compte pour le score du livreur.</p>
      <select id="stars"><option value="5">5 ★</option><option value="4">4 ★</option><option value="3">3 ★</option><option value="2">2 ★</option><option value="1">1 ★</option></select>
      <textarea id="comment" placeholder="Commentaire"></textarea>
      <button class="btn" onclick="submitRate('order', ${o.id}${deliveredRun ? `, ${deliveredRun.id}` : ""})">Noter</button></div>`;
  }

  // Client / supplier pickup & "colis recu" actions
  let pickupActions = "";
  if (state.user && ["client", "fournisseur", "societe", "admin"].includes(state.user.role) && !["CANCELLED", "DELIVERED", "FAILED"].includes(o.status)) {
    const runs = o.delivery_runs || [];
    const activeRun = runs.find(r => r.status && r.status !== "CANCELLED" && r.status !== "DELIVERED");
    if (o.mode === "pickup") {
      // Self-pickup at supplier
      if (o.status !== "PICKUP_IN_PROGRESS" && o.status !== "DELIVERED") {
        pickupActions = `
          <div class="card" style="background:#fff7ed;border:1px solid #fed7aa;">
            <h3>Retrait chez le fournisseur</h3>
            <p>Initialisez la recuperation, puis confirmez quand le colis est en main.</p>
            <button type="button" class="btn" onclick="orderPickupAction(${o.id}, 'init_pickup')">📦 Initialiser la recuperation</button>
          </div>`;
      } else if (o.status === "PICKUP_IN_PROGRESS") {
        pickupActions = `
          <div class="card" style="background:#ecfdf5;border:1px solid #a7f3d0;">
            <h3>Recuperation en cours</h3>
            <p>Avez-vous recu le colis ?</p>
            <button type="button" class="btn ok" onclick="orderPickupAction(${o.id}, 'confirm_received')">✅ Colis recu</button>
          </div>`;
      }
    } else if (activeRun) {
      // Delivery: client can confirm colis recu when pickup initiated or started
      if (["STARTED", "PICKUP_INITIATED", "ACCEPTED"].includes(activeRun.status)) {
        pickupActions = `
          <div class="card" style="background:#f0f9ff;border:1px solid #bae6fd;">
            <h3>Suivi colis</h3>
            <p>Course: <span class="status ${activeRun.status}">${html(activeRun.status)}</span></p>
            ${activeRun.status === "STARTED" || activeRun.status === "ACCEPTED" ? `
              <button type="button" class="btn secondary" onclick="orderPickupAction(${o.id}, 'init_pickup')">📦 Initialiser la recuperation</button>
            ` : ""}
            ${["STARTED", "PICKUP_INITIATED"].includes(activeRun.status) ? `
              <button type="button" class="btn ok" onclick="orderPickupAction(${o.id}, 'confirm_received')">✅ Colis recu</button>
              <p style="font-size:0.8rem;color:var(--muted);margin-top:0.5rem;">Le livreur ou vous pouvez confirmer la reception du colis.</p>
            ` : ""}
          </div>`;
      }
    }
  }

  $("#detail").innerHTML = `
    <p><strong>Code:</strong> ${o.code}</p>
    <p><strong>Statut:</strong> <span class="status ${o.status}">${o.status}</span></p>
    <p><strong>Mode:</strong> ${o.mode === "pickup" ? "Retrait magasin" : "Livraison"}</p>
    <p><strong>Fournisseur:</strong> ${html(o.supplier_name)} (${o.supplier_phone})</p>
    <p><strong>Total:</strong> ${money(o.total)} (${o.payment_method}) — ${o.payment_status}</p>
    <p><strong>Adresse:</strong> ${html(o.delivery_address || "Retrait")}</p>
    <p><strong>OTP validation:</strong> ${o.otp || "—"}</p>
    ${pickupActions}
    <h3>Articles</h3>
    <table><thead><tr><th>Produit</th><th>Qté</th><th>Prix</th></tr></thead><tbody>
    ${o.lines.map(l => `<tr><td>${html(l.product_name)}</td><td>${l.quantity}</td><td>${money(l.unit_price * l.quantity)}</td></tr>`).join("")}
    </tbody></table>
    <h3>Suivi livraison</h3>
    ${o.delivery_runs.length ? o.delivery_runs.map(r => `
      <div class="card">
        <p><strong>Course #${r.id}</strong> — <span class="status ${r.status}">${r.status}</span></p>
        <p>Livreur: ${r.livreur_phone || 'Non assigne'}</p>
        <p>OTP: ${r.otp_code || '—'}</p>
        <div id="map-${r.id}" style="height:250px;border-radius:8px;border:1px solid var(--border);margin-top:0.5rem;"></div>
      </div>
    `).join("") : (o.mode === "pickup" ? "<p>Retrait client — pas de course livreur.</p>" : "<p>Aucune course assignee.</p>")}
    ${ratingHtml}
  `;
  setTimeout(() => {
    (o.delivery_runs || []).forEach(r => {
      if (r.pickup_lat != null) initMap(`map-${r.id}`, r.pickup_lat, r.pickup_lon, r.dropoff_lat, r.dropoff_lon);
    });
  }, 100);
}


async function cancelOrder(orderId) {
  if (!confirm("Êtes-vous sûr de vouloir annuler cette commande ? Des frais de 80% peuvent s'appliquer.")) return;
  try {
    const res = await api(`/api/orders/${orderId}/cancel`, { method: "POST" });
    $("#cancelMsg").innerHTML = `<p class="success">${res.message}. Pénalité: ${money(res.penalty)}. Remboursement: ${money(res.refund)}.</p>`;
    setTimeout(() => go('orders'), 1500);
  } catch (e) {
    $("#cancelMsg").innerHTML = `<p class="error">${e.message}</p>`;
  }
}

async function submitRate(type, id, runId) {
  const stars = parseInt($("#stars").value, 10);
  const comment = ($("#comment") && $("#comment").value) || "";
  const body = { stars, comment };
  if (type === "order") {
    body.order_id = id;
    if (runId) body.run_id = runId;
  } else {
    body.run_id = id;
  }
  try {
    const res = await api("/api/rate", { method: "POST", body });
    const extra = res.livreur_average_rating != null ? `\nNouvelle note moyenne livreur: ★ ${res.livreur_average_rating}` : "";
    alert(`Note enregistree.${extra}`);
    go("orders");
  } catch (e) {
    alert(e.message);
  }
}

function renderCourier(app) {
  app.innerHTML = `
    <div class="card">
      <h2>Demander une course colis</h2>
      <div class="form-row">
        <div><label>Adresse de recuperation</label><input id="pickup" value="Agoe, Lome"></div>
        <div><label>Adresse de livraison</label><input id="dropoff" value="Adidogome, Lome"></div>
      </div>
      <div class="form-row">
        <div><label>Telephone (si invite)</label><input id="cphone" placeholder="+228 XX XX XX XX" value="${state.user ? state.user.phone : ''}"></div>
        <div><label>Paiement</label>
          <select id="cpayment">
            <option value="cash_on_delivery">A la livraison</option>
            <option value="tmoney">Tmoney</option>
            <option value="flooz">Flooz</option>
          </select>
        </div>
      </div>
      <label><input id="fragile" type="checkbox"> Colis fragile</label>
      <button class="btn" onclick="submitCourier()">Estimer et demander</button>
      <div id="msg"></div>
    </div>`;
}

async function submitCourier() {
  try {
    const res = await api("/api/courier-requests", { method: "POST", body: {
      pickup_address: $("#pickup").value, pickup_lat: 6.18, pickup_lon: 1.23,
      dropoff_address: $("#dropoff").value, dropoff_lat: 6.16, dropoff_lon: 1.21,
      is_fragile: $("#fragile").checked, payment_method: $("#cpayment").value,
      guest_phone: $("#cphone").value
    }});
    $("#msg").innerHTML = `<p class="success">Course <strong>${res.code}</strong> creee. Prix: ${money(res.price)}</p>
      <button class="btn" onclick="go('payment', {type:'courier', id:${res.id}, amount:${res.price}})">Payer maintenant</button>`;
  } catch (e) { $("#msg").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function renderSociete(app) {
  app.innerHTML = `<div class="card"><h2>Espace Societe de livraison</h2>
    <div id="soc" class="tabs">
      <div class="tab active" data-tab="orders" onclick="societeTab('orders')">Commandes clients</div>
      <div class="tab" data-tab="fleet" onclick="societeTab('fleet')">Ma flotte</div>
    </div>
    <div id="soc-content"></div>
  </div>`;
  societeTab("orders");
}

async function societeTab(tab) {
  document.querySelectorAll("#soc .tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
  const content = $("#soc-content");
  if (tab === "orders") {
    content.innerHTML = "Chargement...";
    try {
      const [orders, fleet] = await Promise.all([
        api("/api/societe/orders?status=open"),
        api("/api/societe/livreurs")
      ]);
      const fleetOptions = fleet.length
        ? fleet.map(l => {
            const tag = (l.is_internal || l.origin === "internal") ? "interne" : "externe";
            const plate = l.license_plate ? ` · ${l.license_plate}` : "";
            return `<option value="${l.id}">${html([l.first_name, l.last_name].filter(Boolean).join(" ") || l.phone)} — ${html(l.phone)}${html(plate)} (${tag})</option>`;
          }).join("")
        : `<option value="">Aucun livreur dans la flotte</option>`;
      content.innerHTML = `
        <p style="color:var(--muted);font-size:0.9rem;">
          Commandes ou le client vous a choisi a l'avance. Attribuez-les a un livreur de votre flotte.
        </p>
        ${orders.map(o => {
          const run = (o.delivery_runs || []).find(r => r.livreur_id && r.status !== "CANCELLED");
          return `
          <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
              <strong>${html(o.code)}</strong>
              <span class="status ${html(o.status)}">${html(o.status)}</span>
            </div>
            <p>Boutique: <strong>${html(o.supplier_name || "—")}</strong> ${o.supplier_phone ? `— <a href="tel:${html(o.supplier_phone)}">${html(o.supplier_phone)}</a>` : ""}</p>
            <p>Client: ${html(o.client_name || o.client_phone || "—")}
              ${o.client_phone ? ` — <a href="tel:${html(o.client_phone)}">${html(o.client_phone)}</a>` : ""}
            </p>
            <p>Adresse: ${html(o.delivery_address || "—")}</p>
            <p>Total: ${money(o.total)} (produits ${money(o.product_total)} + livr. ${money(o.delivery_fee || 0)})</p>
            ${run
              ? `<p class="tag">Livreur assigne: ${html(run.livreur_phone || "#" + run.livreur_id)} — ${html(run.status)}</p>`
              : `<div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-top:0.5rem;">
                  <select id="soc_liv_${o.id}" style="margin-bottom:0;min-width:200px;">${fleetOptions}</select>
                  <button type="button" class="btn small" onclick="societeAssignLivreur(${o.id})">Attribuer</button>
                </div>`}
          </div>`;
        }).join("") || "<p>Aucune commande en attente pour votre societe.</p>"}
      `;
    } catch (e) {
      content.innerHTML = `<p class="error">${html(e.message)}</p>`;
    }
  } else if (tab === "fleet") {
    content.innerHTML = "Chargement...";
    try {
      const [fleet, all] = await Promise.all([
        api("/api/societe/livreurs"),
        api("/api/livreurs")
      ]);
      const fleetIds = new Set(fleet.map(l => l.id));
      const available = all.filter(l => !fleetIds.has(l.id) && !l.employer_societe_id);
      const internals = fleet.filter(l => l.is_internal || l.origin === "internal");
      const externals = fleet.filter(l => !(l.is_internal || l.origin === "internal"));
      const card = (l) => {
        const internal = l.is_internal || l.origin === "internal";
        return `
          <div class="card" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.5rem;">
            <div>
              <strong>${html([l.first_name, l.last_name].filter(Boolean).join(" ") || l.phone)}</strong>
              <span class="tag" style="margin-left:0.35rem;${internal ? "background:#dbeafe;color:#1d4ed8;" : "background:#fef3c7;color:#92400e;"}">
                ${internal ? "Ressource societe" : "Livreur externe (pro)"}
              </span>
              <div>${html(l.phone)} — ★${(l.average_rating || 0).toFixed(1)} — ${l.total_deliveries || 0} livr.</div>
              <div style="font-size:0.9rem;color:var(--muted);">
                Vehicule: <strong>${html(l.vehicle_type || "—")}</strong>
                · Plaque: <strong>${html(l.license_plate || "—")}</strong>
              </div>
            </div>
            <div style="display:flex;gap:0.35rem;flex-wrap:wrap;">
              <button class="btn small secondary" type="button" onclick="editSocieteLivreur(${l.id}, ${internal ? "true" : "false"}, '${html(l.first_name || "")}', '${html(l.last_name || "")}', '${html(l.vehicle_type || "")}', '${html(l.license_plate || "")}')">Modifier</button>
              <button class="btn small danger" type="button" onclick="unlinkSocieteLivreur(${l.id})">${internal ? "Retirer / desactiver" : "Retirer"}</button>
            </div>
          </div>`;
      };
      content.innerHTML = `
        <p style="color:var(--muted);font-size:0.9rem;">
          <strong>Ressources societe</strong> = livreurs crees par vous (plaque / vehicule). 
          <strong>Livreurs externes</strong> = pros inscrits seuls, rattaches a votre flotte.
        </p>

        <div class="card" style="background:#eff6ff;border:1px solid #bfdbfe;">
          <h3 style="margin:0 0 0.5rem;">Ajouter un livreur interne (ressource)</h3>
          <div class="form-row">
            <div><label>Prenom</label><input id="intFirst" placeholder="Mensah"></div>
            <div><label>Nom</label><input id="intLast" placeholder="Course"></div>
          </div>
          <div class="form-row">
            <div><label>Telephone</label><input id="intPhone" placeholder="+228..." required></div>
            <div><label>Mot de passe</label><input id="intPwd" type="password" placeholder="min. 6 caracteres" required></div>
          </div>
          <div class="form-row">
            <div><label>Type de vehicule</label><input id="intVehicle" placeholder="Moto, Voiture..."></div>
            <div><label>Plaque d'immatriculation *</label><input id="intPlate" placeholder="TG-XXXX-XX" required></div>
          </div>
          <button class="btn" type="button" onclick="createInternalLivreur()">Creer et ajouter a la flotte</button>
          <div id="intMsg" style="margin-top:0.5rem;"></div>
        </div>

        <h3 style="margin-top:1.25rem;">Ressources societe (${internals.length})</h3>
        ${internals.map(card).join("") || "<p>Aucune ressource interne pour le moment.</p>"}

        <h3 style="margin-top:1.25rem;">Livreurs externes rattaches (${externals.length})</h3>
        ${externals.map(card).join("") || "<p>Aucun livreur externe rattache.</p>"}

        <h3 style="margin-top:1.25rem;">Rattacher un livreur pro externe</h3>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">
          <select id="addSocLiv" style="margin-bottom:0;min-width:220px;">
            ${available.length
              ? available.map(l => `<option value="${l.id}">${html([l.first_name, l.last_name].filter(Boolean).join(" ") || l.phone)} — ${html(l.phone)}${l.license_plate ? " · " + html(l.license_plate) : ""}</option>`).join("")
              : `<option value="">Aucun livreur externe disponible</option>`}
          </select>
          <button class="btn secondary" type="button" onclick="linkSocieteLivreur()">Rattacher</button>
        </div>
      `;
    } catch (e) {
      content.innerHTML = `<p class="error">${html(e.message)}</p>`;
    }
  }
}

async function societeAssignLivreur(oid) {
  try {
    const sel = $(`#soc_liv_${oid}`);
    const livreurId = sel ? parseInt(sel.value, 10) : null;
    if (!livreurId) { alert("Choisissez un livreur de votre flotte"); return; }
    const res = await api(`/api/orders/${oid}/assign-livreur`, {
      method: "POST",
      body: { livreur_id: livreurId }
    });
    alert(`Livreur assigne (${res.livreur_name || ""}). OTP: ${res.otp || "—"}`);
    societeTab("orders");
  } catch (e) { alert(e.message); }
}

async function createInternalLivreur() {
  const msg = $("#intMsg");
  try {
    const body = {
      create: true,
      first_name: ($("#intFirst") && $("#intFirst").value || "").trim(),
      last_name: ($("#intLast") && $("#intLast").value || "").trim(),
      phone: ($("#intPhone") && $("#intPhone").value || "").trim(),
      password: ($("#intPwd") && $("#intPwd").value || ""),
      vehicle_type: ($("#intVehicle") && $("#intVehicle").value || "").trim(),
      license_plate: ($("#intPlate") && $("#intPlate").value || "").trim(),
    };
    if (!body.phone || !body.password) {
      if (msg) msg.innerHTML = `<p class="error">Telephone et mot de passe requis.</p>`;
      return;
    }
    if (!body.license_plate) {
      if (msg) msg.innerHTML = `<p class="error">Plaque d'immatriculation requise.</p>`;
      return;
    }
    const res = await api("/api/societe/livreurs", { method: "POST", body });
    if (msg) msg.innerHTML = `<p class="success">${html(res.message || "Livreur interne cree.")}</p>`;
    setTimeout(() => societeTab("fleet"), 700);
  } catch (e) {
    if (msg) msg.innerHTML = `<p class="error">${html(e.message)}</p>`;
  }
}

async function editSocieteLivreur(id, isInternal, first, last, vehicle, plate) {
  const newVehicle = prompt("Type de vehicule :", vehicle || "");
  if (newVehicle === null) return;
  const newPlate = prompt("Plaque d'immatriculation :", plate || "");
  if (newPlate === null) return;
  if (isInternal && !(newPlate || "").trim()) {
    alert("Plaque requise pour une ressource societe.");
    return;
  }
  const body = {
    vehicle_type: (newVehicle || "").trim(),
    license_plate: (newPlate || "").trim(),
  };
  if (isInternal) {
    const newFirst = prompt("Prenom :", first || "");
    if (newFirst === null) return;
    const newLast = prompt("Nom :", last || "");
    if (newLast === null) return;
    body.first_name = (newFirst || "").trim();
    body.last_name = (newLast || "").trim();
  }
  try {
    await api(`/api/societe/livreurs/${id}`, { method: "PUT", body });
    societeTab("fleet");
  } catch (e) { alert(e.message); }
}

async function linkSocieteLivreur() {
  try {
    const sel = $("#addSocLiv");
    const id = sel ? parseInt(sel.value, 10) : null;
    if (!id) { alert("Choisissez un livreur externe"); return; }
    await api("/api/societe/livreurs", { method: "POST", body: { livreur_id: id } });
    alert("Livreur externe rattache a la flotte.");
    societeTab("fleet");
  } catch (e) { alert(e.message); }
}

async function unlinkSocieteLivreur(livreurId) {
  try {
    if (!confirm("Retirer ce livreur de votre flotte ?\n(Les ressources internes seront aussi desactivees.)\n\nOK = Oui  |  Annuler = Non")) return;
    await api("/api/societe/livreurs", { method: "DELETE", body: { livreur_id: livreurId } });
    societeTab("fleet");
  } catch (e) { alert(e.message); }
}

async function renderSupplier(app) {
  app.innerHTML = `<div class="card"><h2>Espace Fournisseur <span id="supOpenBadge"></span></h2>
    <div id="sup" class="tabs">
      <div class="tab active" data-tab="orders" onclick="supplierTab('orders')">Commandes</div>
      <div class="tab" data-tab="sales" onclick="supplierTab('sales')">Historique ventes</div>
      <div class="tab" data-tab="livreurs" onclick="supplierTab('livreurs')">Livreurs boutique</div>
      <div class="tab" data-tab="products" onclick="supplierTab('products')">Mes produits</div>
      <div class="tab" data-tab="add" onclick="supplierTab('add')">Ajouter un produit</div>
      <div class="tab" data-tab="hours" onclick="supplierTab('hours')">Horaires</div>
      <div class="tab" data-tab="kyc" onclick="supplierTab('kyc')">Mes pieces KYC</div>
    </div>
    <div id="sup-content"></div>
  </div>`;
  try {
    const res = await api("/api/supplier/opening-hours");
    const badge = $("#supOpenBadge");
    if (badge && !Array.isArray(res)) {
      badge.innerHTML = res.open_now
        ? `<span class="badge-open">Ouvert</span>`
        : `<span class="badge-closed">Ferme</span>`;
    }
  } catch (e) { /* ignore */ }
  supplierTab("orders");
}

async function supplierTab(tab) {
  document.querySelectorAll("#sup .tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
  const content = $("#sup-content");
  
  if (tab === "orders") {
    content.innerHTML = "Chargement...";
    const orders = await api("/api/orders");
    content.innerHTML = orders.map(o => {
      const modeLabel = o.mode === "pickup" ? "🏪 Retrait client" : "🚚 Livraison";
      const payOk = o.payment_ready || o.payment_status === "paid";
      const payLabel = o.payment_status === "paid"
        ? "Paye"
        : (o.payment_method === "pay_at_pickup" ? "A payer au retrait" : o.payment_method === "cash_on_delivery" ? "A payer a la livraison" : o.payment_status);
      const run = (o.delivery_runs || []).find(r => r.livreur_id && r.status !== "CANCELLED");
      let dispatchBlock = "";

      if (o.mode === "delivery" && !run && o.status !== "CANCELLED" && o.status !== "DELIVERED") {
        if (o.can_assign_shop_livreur || o.has_shop_livreurs) {
          dispatchBlock = `
            <div style="margin-top:0.75rem;padding:0.75rem;background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;">
              <strong>Livreurs de la boutique</strong>
              <p style="font-size:0.85rem;margin:0.35rem 0;">Choisissez un livreur associe a votre boutique.</p>
              <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">
                <select id="liv_shop_${o.id}" style="margin-bottom:0;min-width:180px;"><option value="">Chargement...</option></select>
                <button class="btn small" type="button" onclick="assignLivreur(${o.id}, 'liv_shop_${o.id}')">Attribuer au livreur boutique</button>
              </div>
            </div>`;
        } else if (o.can_init_handover) {
          dispatchBlock = `
            <div style="margin-top:0.75rem;padding:0.75rem;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;">
              <strong>Pas de livreur boutique</strong>
              <p style="font-size:0.85rem;margin:0.35rem 0;">
                Initialisez la reception du colis : un <strong>livreur autonome / plateforme</strong> pourra s'attribuer la course,
                ou l'<strong>admin</strong> pourra l'attribuer.
              </p>
              <button type="button" class="btn" onclick="supplierInitHandover(${o.id})">
                📦 Initialiser la reception du colis (ouvrir a la plateforme)
              </button>
            </div>`;
        } else if (o.open_for_platform_claim || o.handover_initialized) {
          dispatchBlock = `
            <div style="margin-top:0.75rem;padding:0.75rem;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;">
              <strong>✅ Ouverte a la plateforme</strong>
              <p style="font-size:0.85rem;margin:0.35rem 0;">En attente qu'un livreur s'attribue la course ou qu'un admin l'assigne.</p>
            </div>`;
        }
      } else if (o.mode === "pickup" && o.can_init_handover) {
        dispatchBlock = `
          <div style="margin-top:0.75rem;padding:0.75rem;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;">
            <strong>Retrait client</strong>
            <p style="font-size:0.85rem;margin:0.35rem 0;">Initialisez le retrait pour que le client vienne recuperer le colis.</p>
            <button type="button" class="btn" onclick="supplierInitHandover(${o.id})">📦 Initialiser le retrait client</button>
          </div>`;
      } else if (o.handover_initialized && o.status !== "DELIVERED") {
        const who = o.mode === "pickup"
          ? "Client — en attente / « Colis recu »"
          : (run ? `Livreur ${html(run.livreur_phone || "#" + run.livreur_id)}` : "Livreur plateforme (en attente)");
        dispatchBlock = `
          <div style="margin-top:0.75rem;padding:0.75rem;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;">
            <strong>✅ Reception initialisee</strong>
            <p style="font-size:0.85rem;margin:0.35rem 0;">${who}</p>
          </div>`;
      } else if (!payOk && !["CANCELLED", "DELIVERED", "FAILED"].includes(o.status)) {
        dispatchBlock = `<p class="error" style="margin-top:0.5rem;font-size:0.85rem;">Paiement non confirme — attribution / retrait non disponible.</p>`;
      }

      if (run) {
        dispatchBlock += `<p class="tag" style="margin-top:0.5rem;">Livreur: ${html(run.livreur_phone || "#" + run.livreur_id)} — ${html(run.status)}</p>`;
      }

      return `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
          <strong>${o.code}</strong>
          <span class="status ${o.status}">${o.status}</span>
        </div>
        <p><span class="tag">${modeLabel}</span>
          <span class="tag">${html(payLabel)}</span>
          ${o.has_shop_livreurs ? `<span class="tag">${o.shop_livreur_count} livreur(s) boutique</span>` : `<span class="tag">Sans livreur boutique</span>`}
        </p>
        <p><strong>Ma vente (produits):</strong> ${money(o.product_total)}
          ${o.mode === "delivery" ? ` <span style="color:var(--muted);font-size:0.85rem;">· frais livr. ${money(o.delivery_fee || 0)} (livreur)</span>` : ""}
        </p>
        <p>Client: ${html(o.client_name || o.client_phone || "Invite")}
          ${o.client_phone ? ` — <a href="tel:${html(o.client_phone)}">${html(o.client_phone)}</a>` : ""}
        </p>
        <p>Adresse: ${html(o.delivery_address || "Retrait magasin")}</p>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-top:0.5rem;">
          <select id="st_${o.id}" style="margin-bottom:0;">
            ${["CREATED","PREPARING","PICKUP_IN_PROGRESS","OUT_FOR_DELIVERY","DELIVERED","CANCELLED","FAILED"].map(s => `<option value="${s}" ${o.status === s ? "selected" : ""}>${s}</option>`).join("")}
          </select>
          <button class="btn small" type="button" onclick="updateOrderStatus(${o.id})">Mettre a jour</button>
        </div>
        ${dispatchBlock}
      </div>
    `;
    }).join("") || "<p>Aucune commande.</p>";
    // Populate shop livreur selects
    try {
      const shopLivreurs = await api("/api/supplier/livreurs");
      document.querySelectorAll("[id^='liv_shop_']").forEach(sel => {
        sel.innerHTML = shopLivreurs.length
          ? shopLivreurs.map(l => `<option value="${l.id}">${html([l.first_name, l.last_name].filter(Boolean).join(" ") || l.phone)} ★${(l.average_rating || 0).toFixed(1)}</option>`).join("")
          : `<option value="">Aucun livreur boutique</option>`;
      });
    } catch (e) { console.error(e); }
  } else if (tab === "sales") {
    const from = $("#salesFrom") ? $("#salesFrom").value : (state.salesFrom || "");
    const to = $("#salesTo") ? $("#salesTo").value : (state.salesTo || "");
    state.salesFrom = from;
    state.salesTo = to;
    content.innerHTML = "Chargement...";
    try {
      await renderSupplierSalesHistory(content, from, to);
    } catch (e) {
      content.innerHTML = `<p class="error">${html(e.message)}</p>`;
    }
  } else if (tab === "livreurs") {
    content.innerHTML = "Chargement...";
    try {
      const [shop, all] = await Promise.all([
        api("/api/supplier/livreurs"),
        api("/api/livreurs")
      ]);
      const shopIds = new Set(shop.map(l => l.id));
      const available = all.filter(l => !shopIds.has(l.id));
      content.innerHTML = `
        <h3>Livreurs associes a ma boutique</h3>
        <p style="color:var(--muted);font-size:0.9rem;">
          S'il y a des livreurs associes, vous les choisissez pour chaque commande.
          Sinon, apres initialisation du colis, un livreur plateforme peut s'attribuer la course (ou l'admin l'attribue).
        </p>
        ${shop.map(l => `
          <div class="card" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
            <div>
              <strong>${html([l.first_name, l.last_name].filter(Boolean).join(" ") || l.phone)}</strong>
              <div>${html(l.phone)} — ★${(l.average_rating || 0).toFixed(1)} — ${l.total_deliveries || 0} livraisons</div>
            </div>
            <button class="btn small danger" type="button" onclick="unlinkShopLivreur(${l.id})">Retirer</button>
          </div>
        `).join("") || "<p>Aucun livreur associe pour le moment.</p>"}
        <h3 style="margin-top:1.25rem;">Ajouter un livreur plateforme</h3>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">
          <select id="addShopLiv" style="margin-bottom:0;min-width:220px;">
            ${available.length
              ? available.map(l => `<option value="${l.id}">${html([l.first_name, l.last_name].filter(Boolean).join(" ") || l.phone)} — ${html(l.phone)}</option>`).join("")
              : `<option value="">Aucun livreur disponible</option>`}
          </select>
          <button class="btn" type="button" onclick="linkShopLivreur()">Associer a la boutique</button>
        </div>
      `;
    } catch (e) {
      content.innerHTML = `<p class="error">${html(e.message)}</p>`;
    }
  } else if (tab === "products") {
    content.innerHTML = "Chargement...";
    const prods = await api("/api/supplier/products");
    content.innerHTML = prods.map(p => `
      <div class="card product" style="display:flex;flex-direction:row;gap:1rem;align-items:flex-start;">
        <img src="${p.image_url || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22%3E%3Crect width=%22100%25%22 height=%22100%25%22 fill=%22%23eef2f7%22/%3E%3C/svg%3E'}" style="width:100px;height:100px;object-fit:cover;border-radius:8px;background:#eef2f7;">
        <div style="flex:1;">
          <strong>${html(p.name)}</strong> <span class="tag">${html(p.category_name)}</span>
          <div class="price">${money(p.price)} — Stock: ${p.stock}</div>
          <div>${html(p.description || '')}</div>
          <div style="margin-top:0.5rem;display:flex;gap:0.5rem;flex-wrap:wrap;">
            <button class="btn small" onclick="openProductModal(${p.id})">Modifier</button>
            <button class="btn small secondary" onclick="openImageUploadModal(${p.id}, '${html(p.name).replace(/'/g, "\'")}')">📷 Image</button>
            <button class="btn small danger" onclick="deleteProduct(${p.id})">Supprimer</button>
          </div>
        </div>
      </div>
    `).join("") || "<p>Aucun produit.</p>";
  } else if (tab === "hours") {
    // ISO: 0=Lundi ... 6=Dimanche (doit matcher Python datetime.weekday)
    const dayNames = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
    content.innerHTML = `
      <h3>Mes plages horaires</h3>
      <p style="color:var(--muted);font-size:0.85rem;">
        Definissez vos jours et heures d'ouverture (fuseau Afrique/Lome).
        Hors plage, les clients ne peuvent pas commander. Mettez ouverture = fermeture pour un jour ferme.
      </p>
      <div id="hoursStatus" style="margin-bottom:0.75rem;"></div>
      <form id="hoursForm" onsubmit="event.preventDefault(); saveOpeningHours();">
        <div class="hours-table">
          <div class="hours-row hours-head">
            <span>Jour</span>
            <span>Ouverture</span>
            <span></span>
            <span>Fermeture</span>
            <span>Jour</span>
          </div>
          ${[0,1,2,3,4,5,6].map(d => `
            <div class="hours-row" id="hours_row_${d}">
              <label class="hours-day" for="open_${d}">${dayNames[d]}</label>
              <input type="time" id="open_${d}" value="08:00" required onchange="refreshHoursRowState(${d})">
              <span class="hours-sep">→</span>
              <input type="time" id="close_${d}" value="20:00" required onchange="refreshHoursRowState(${d})">
              <span class="hours-day-state" id="day_state_${d}">—</span>
            </div>
          `).join("")}
        </div>
        <button type="submit" class="btn" style="margin-top:0.75rem;">Enregistrer les horaires</button>
      </form>
      <div id="hmsg"></div>
    `;
    // Load existing hours
    try {
      const res = await api("/api/supplier/opening-hours");
      const hours = Array.isArray(res) ? res : (res.hours || []);
      hours.forEach(h => {
        const openInput = $(`#open_${h.day_of_week}`);
        const closeInput = $(`#close_${h.day_of_week}`);
        if (openInput) openInput.value = h.open_time;
        if (closeInput) closeInput.value = h.close_time;
      });
      [0,1,2,3,4,5,6].forEach(d => refreshHoursRowState(d));
      if (!Array.isArray(res) && res.server_local_time != null) {
        const today = res.today_day_of_week;
        if (today != null && $(`#hours_row_${today}`)) {
          $(`#hours_row_${today}`).classList.add("hours-today");
        }
        const todayHours = (res.today_hours || []).map(h =>
          h.closed_day ? "ferme toute la journee" : `${h.open_time} → ${h.close_time}`
        ).join(", ") || "aucune plage";
        $("#hoursStatus").innerHTML = `
          <div class="open-banner ${res.open_now ? "is-open" : "is-closed"}">
            <div class="open-banner-status">${res.open_now ? "🟢 OUVERT" : "🔴 FERME"}</div>
            <div class="open-banner-meta">
              ${html(res.server_weekday)} ${html(res.server_local_time)}
              · Aujourd'hui : ${html(todayHours)}
            </div>
          </div>`;
      }
    } catch (e) { console.log(e); }
  } else if (tab === "kyc") {
    content.innerHTML = `
      <h3>Mes pieces KYC</h3>
      <p style="color:var(--muted);font-size:0.85rem;">Televersez votre piece d'identite obligatoire et votre CFE (facultatif). Votre compte sera re-valide par l'admin.</p>
      <form id="kycForm" onsubmit="event.preventDefault(); uploadKYC();">
        <label>Piece d'identite (PDF, PNG, JPG) *</label>
        <input type="file" id="kycId" accept=".pdf,.png,.jpg,.jpeg" required>
        <label>Photocopie CFE (PDF, PNG, JPG)</label>
        <input type="file" id="kycCfe" accept=".pdf,.png,.jpg,.jpeg">
        <button type="submit" class="btn">Soumettre les pieces</button>
      </form>
      <div id="kycMsg"></div>
      <div id="kycStatus" style="margin-top:1rem;"></div>
    `;
  } else if (tab === "add") {
    const cats = await api("/api/categories");
    content.innerHTML = `
      <h3>Ajouter un produit</h3>
      <form id="addProductForm" onsubmit="event.preventDefault(); createProductWithImage();">
        <label>Nom</label><input id="pname" required>
        <label>Description</label><textarea id="pdesc"></textarea>
        <div class="form-row">
          <div><label>Prix (XOF)</label><input id="pprice" type="number" min="0" required></div>
          <div><label>Stock</label><input id="pstock" type="number" min="0" required></div>
        </div>
        <label>Categorie</label>
        <select id="pcat">${cats.map(c => `<option value="${c.id}">${html(c.name)}</option>`).join("")}</select>
        <label><input id="pfragile" type="checkbox"> Produit fragile</label>
        <label>Image du produit (optionnel)</label>
        <input type="file" id="pimageFile" accept="image/png,image/jpeg,image/gif,image/webp">
        <div style="font-size:0.8rem;color:var(--muted);margin-bottom:0.75rem;">Formats: PNG, JPG, GIF, WebP. Max 5 Mo.</div>
        <label>Ou URL image externe</label><input id="pimageUrl" placeholder="https://...">
        <button type="submit" class="btn">Enregistrer</button>
      </form>
      <div id="pmsg"></div>
    `;
  }
}

function formatSaleDayLabel(dateStr) {
  try {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString("fr-FR", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric"
    });
  } catch {
    return dateStr;
  }
}

async function renderSupplierSalesHistory(content, from = "", to = "") {
  const qs = new URLSearchParams();
  if (from) qs.set("from", from);
  if (to) qs.set("to", to);
  const url = "/api/supplier/sales-history" + (qs.toString() ? `?${qs}` : "");
  const data = await api(url);
  const summary = data.summary || {};
  const days = data.days || [];

  const wallet = data.wallet || {};
  content.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:0.75rem;margin-bottom:1rem;">
      <div>
        <h3 style="margin:0;">Historique des ventes</h3>
        <p style="color:var(--muted);font-size:0.9rem;margin:0.35rem 0 0;">
          CA boutique = <strong>prix des produits uniquement</strong> (les frais de livraison vont au livreur).
        </p>
      </div>
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:flex-end;">
        <div>
          <label style="font-size:0.8rem;">Du</label>
          <input type="date" id="salesFrom" value="${html(from)}" style="margin-bottom:0;">
        </div>
        <div>
          <label style="font-size:0.8rem;">Au</label>
          <input type="date" id="salesTo" value="${html(to)}" style="margin-bottom:0;">
        </div>
        <button type="button" class="btn small" onclick="supplierTab('sales')">Filtrer</button>
        <button type="button" class="btn small secondary" onclick="clearSalesFilter()">Tout</button>
      </div>
    </div>

    <div class="grid grid-3" style="gap:0.75rem;margin-bottom:1rem;">
      <div class="card" style="margin:0;padding:0.85rem;background:#eff6ff;border:1px solid #bfdbfe;">
        <div style="font-size:0.8rem;color:var(--muted);">Commandes</div>
        <div style="font-size:1.25rem;font-weight:800;">${summary.orders_count || 0}</div>
        <div style="font-size:0.8rem;color:var(--muted);">${summary.delivered_count || 0} livrees · ${summary.cancelled_count || 0} annulees</div>
      </div>
      <div class="card" style="margin:0;padding:0.85rem;background:#ecfdf5;border:1px solid #a7f3d0;">
        <div style="font-size:0.8rem;color:var(--muted);">Mes ventes produits (CA)</div>
        <div style="font-size:1.25rem;font-weight:800;color:#047857;">${money(summary.product_total || summary.supplier_sales || 0)}</div>
        <div style="font-size:0.8rem;color:var(--muted);">Hors frais livraison (${money(summary.delivery_total || 0)} → livreur)</div>
      </div>
      <div class="card" style="margin:0;padding:0.85rem;background:#fff7ed;border:1px solid #fed7aa;">
        <div style="font-size:0.8rem;color:var(--muted);">Solde retirable (ventes)</div>
        <div style="font-size:1.25rem;font-weight:800;color:#c2410c;">${money(wallet.available || 0)}</div>
        <button type="button" class="btn small" style="margin-top:0.5rem;" onclick="initWalletWithdraw('fournisseur')">Initialiser un retrait</button>
      </div>
    </div>
    <div id="walletMsg"></div>

    ${days.map(day => `
      <div class="card sales-day" style="margin-bottom:1rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem;">
          <div>
            <strong style="text-transform:capitalize;">📅 ${html(formatSaleDayLabel(day.date))}</strong>
            <div style="font-size:0.85rem;color:var(--muted);">
              ${day.orders_count} commande(s) · ${day.delivered_count || 0} livree(s)
              ${day.cancelled_count ? ` · ${day.cancelled_count} annulee(s)` : ""}
            </div>
          </div>
          <div style="text-align:right;">
            <div style="font-weight:800;">${money(day.product_total || 0)}</div>
            <div style="font-size:0.8rem;color:var(--muted);">Ventes produits</div>
          </div>
        </div>
        <div style="overflow-x:auto;">
          <table class="sales-table">
            <thead>
              <tr>
                <th>Heure</th>
                <th>Commande</th>
                <th>Client</th>
                <th>Articles</th>
                <th>Mode</th>
                <th>Statut</th>
                <th>Paiement</th>
                <th style="text-align:right;">Ma vente</th>
              </tr>
            </thead>
            <tbody>
              ${(day.orders || []).map(o => {
                const time = o.created_at ? new Date(o.created_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "—";
                const items = (o.lines || []).map(l => `${html(l.product_name || "?")} ×${l.quantity}`).join(", ") || "—";
                const modeLabel = o.mode === "pickup" ? "Retrait" : "Livraison";
                const payLabel = o.payment_status === "paid"
                  ? "Paye"
                  : (o.payment_method === "pay_at_pickup" ? "Au retrait"
                    : o.payment_method === "cash_on_delivery" ? "A la livraison"
                    : html(o.payment_status || "—"));
                return `
                  <tr>
                    <td>${html(time)}</td>
                    <td><strong>${html(o.code)}</strong></td>
                    <td>${html(o.client_name || o.client_phone || "Invite")}</td>
                    <td style="max-width:220px;font-size:0.85rem;">${items}</td>
                    <td>${modeLabel}</td>
                    <td><span class="status ${html(o.status)}">${html(o.status)}</span></td>
                    <td>${payLabel}</td>
                    <td style="text-align:right;font-weight:700;">${money(o.product_total)}</td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `).join("") || `<p>Aucune vente sur cette periode.</p>`}
  `;
}

async function initWalletWithdraw(roleHint) {
  const msg = $("#walletMsg") || $("#pmsg");
  try {
    const wallet = await api("/api/wallet");
    const available = Number(wallet.available || 0);
    if (available <= 0) {
      alert(`Aucun solde retirable (${wallet.label || "portefeuille"}).`);
      return;
    }
    const raw = prompt(
      `Initialiser un retrait — ${wallet.label}\nDisponible: ${available} XOF\n\nMontant a retirer:`,
      String(available)
    );
    if (raw === null) return;
    const amount = parseFloat(String(raw).replace(/\s/g, "").replace(",", "."));
    if (!(amount > 0)) {
      alert("Montant invalide");
      return;
    }
    if (amount > available) {
      alert(`Montant trop eleve. Disponible: ${available} XOF`);
      return;
    }
    if (!confirm(`Confirmer le retrait de ${amount} XOF ?\n\nOK = Oui  |  Annuler = Non`)) return;
    const res = await api("/api/wallet/withdraw", {
      method: "POST",
      body: { amount, note: `Retrait ${wallet.label}` }
    });
    const text = `${res.message || "Retrait OK"} — reste ${money((res.wallet || {}).available || 0)}`;
    alert(text);
    if (msg) msg.innerHTML = `<p class="success">${html(text)}</p>`;
    if (roleHint === "fournisseur") {
      supplierTab("sales");
    } else if (state.user && state.user.role === "livreur") {
      // Refresh portefeuille tab if open, else profile
      const walletTab = document.querySelector('#livreur-tabs .tab[data-tab="wallet"]');
      if (walletTab && walletTab.classList.contains("active")) {
        livreurTab("wallet");
      } else if ($("#livreur-tabs")) {
        livreurTab("wallet");
      } else {
        renderProfile($("#app"));
      }
    }
  } catch (e) {
    alert(e.message);
    if (msg) msg.innerHTML = `<p class="error">${html(e.message)}</p>`;
  }
}

// Expose for inline onclick handlers
window.initWalletWithdraw = initWalletWithdraw;

function clearSalesFilter() {
  state.salesFrom = "";
  state.salesTo = "";
  const a = $("#salesFrom");
  const b = $("#salesTo");
  if (a) a.value = "";
  if (b) b.value = "";
  supplierTab("sales");
}

async function updateOrderStatus(oid) {
  try {
    await api(`/api/supplier/orders/${oid}/status`, { method: "POST", body: { status: $(`#st_${oid}`).value } });
    supplierTab("orders");
  } catch (e) { alert(e.message); }
}

async function supplierInitHandover(oid) {
  try {
    if (!confirm(
      "Initialiser la reception / le retrait du colis ?\n\n" +
      "• Retrait client : le client vient chercher le colis\n" +
      "• Sans livreur boutique : un livreur plateforme pourra s'attribuer la course (ou l'admin)\n\n" +
      "OK = Oui  |  Annuler = Non"
    )) return;
    const res = await api(`/api/supplier/orders/${oid}/init-handover`, { method: "POST", body: {} });
    alert(res.message || "Reception initialisee.");
    supplierTab("orders");
  } catch (e) { alert(e.message); }
}

async function linkShopLivreur() {
  try {
    const sel = $("#addShopLiv");
    const id = sel ? parseInt(sel.value, 10) : null;
    if (!id) { alert("Choisissez un livreur"); return; }
    await api("/api/supplier/livreurs", { method: "POST", body: { livreur_id: id } });
    alert("Livreur associe a la boutique.");
    supplierTab("livreurs");
  } catch (e) { alert(e.message); }
}

async function unlinkShopLivreur(livreurId) {
  try {
    if (!confirm("Retirer ce livreur de la boutique ?\n\nOK = Oui  |  Annuler = Non")) return;
    await api("/api/supplier/livreurs", { method: "DELETE", body: { livreur_id: livreurId } });
    supplierTab("livreurs");
  } catch (e) { alert(e.message); }
}

async function assignLivreur(oid, selectId) {
  try {
    let livreurId = null;
    if (selectId) {
      const sel = document.getElementById(selectId);
      if (sel) livreurId = parseInt(sel.value, 10);
    }
    if (!livreurId) {
      const livreurs = await api("/api/livreurs");
      if (!livreurs.length) { alert("Aucun livreur disponible"); return; }
      livreurId = livreurs[0].id;
    }
    const res = await api(`/api/orders/${oid}/assign-livreur`, {
      method: "POST",
      body: { livreur_id: livreurId }
    });
    alert(`Livreur assigne (${res.livreur_name || ""}). OTP: ${res.otp}`);
    if (state.user && state.user.role === "admin") adminTab("dispatch");
    else supplierTab("orders");
  } catch (e) { alert(e.message); }
}

async function claimOrderAsLivreur(orderId) {
  try {
    const res = await api(`/api/livreur/orders/${orderId}/claim`, { method: "POST", body: {} });
    alert(`Mission prise en charge. OTP: ${res.otp}`);
    livreurTab("missions");
  } catch (e) { alert(e.message); }
}

async function createProductWithImage() {
  const fileInput = $("#pimageFile");
  const hasFile = fileInput.files && fileInput.files[0];
  
  let body = {
    name: $("#pname").value, description: $("#pdesc").value,
    price: parseFloat($("#pprice").value) || 0, stock: parseInt($("#pstock").value) || 0,
    category_id: parseInt($("#pcat").value), fragile: $("#pfragile").checked,
    image_url: $("#pimageUrl").value || null
  };
  
  try {
    const created = await api("/api/supplier/products", { method: "POST", body });
    
    // Upload image if selected
    if (hasFile) {
      const file = fileInput.files[0];
      if (file.size > 5 * 1024 * 1024) {
        throw new Error("Image trop lourde (max 5 Mo)");
      }
      const formData = new FormData();
      formData.append("image", file);
      const res = await fetch(API + `/api/v1/merchant/products/${created.id}/image`, {
        method: "POST",
        body: formData,
        credentials: "same-origin"
      });
      const up = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(up.error || "Erreur upload image");
      }
    }
    
    $("#pmsg").innerHTML = `<p class="success">Produit cree${hasFile ? ' avec image' : ''}.</p>`;
    document.getElementById("addProductForm").reset();
    state.products = []; // force catalogue refresh
    supplierTab("products");
  } catch (e) { $("#pmsg").innerHTML = `<p class="error">${e.message}</p>`; }
}

// Legacy function kept for compatibility

function refreshHoursRowState(day) {
  const openEl = $(`#open_${day}`);
  const closeEl = $(`#close_${day}`);
  const stateEl = $(`#day_state_${day}`);
  if (!openEl || !closeEl || !stateEl) return;
  const open = openEl.value;
  const close = closeEl.value;
  if (!open || !close) {
    stateEl.textContent = "—";
    stateEl.className = "hours-day-state";
    return;
  }
  if (open === close) {
    stateEl.textContent = "Ferme";
    stateEl.className = "hours-day-state is-closed";
  } else {
    stateEl.textContent = `${open}–${close}`;
    stateEl.className = "hours-day-state is-open";
  }
}

async function saveOpeningHours() {
  // ISO Monday=0 .. Sunday=6
  const days = [0, 1, 2, 3, 4, 5, 6];
  const data = days.map(d => ({
    day_of_week: d,
    open_time: $(`#open_${d}`).value,
    close_time: $(`#close_${d}`).value
  })).filter(d => d.open_time && d.close_time);
  try {
    const res = await api("/api/supplier/opening-hours", { method: "POST", body: data });
    $("#hmsg").innerHTML = `<p class="success">Horaires enregistres. ${res.open_now === false ? "Attention: vous etes actuellement FERME selon ces horaires." : "Vous etes OUVERT maintenant."}</p>`;
    supplierTab("hours");
  } catch (e) { $("#hmsg").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function uploadKYC() {
  const idFile = $("#kycId").files[0];
  if (!idFile) {
    $("#kycMsg").innerHTML = `<p class="error">Veuillez choisir une piece d'identite.</p>`;
    return;
  }
  const formData = new FormData();
  formData.append("id_document", idFile);
  const cfeFile = $("#kycCfe").files[0];
  if (cfeFile) formData.append("cfe_document", cfeFile);
  try {
    const res = await fetch(API + "/api/v1/merchant/kyc", {
      method: "POST", body: formData, credentials: "same-origin"
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Erreur KYC");
    $("#kycMsg").innerHTML = `<p class="success">Pieces KYC soumises. En attente de validation admin.</p>`;
  } catch (e) { $("#kycMsg").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function createProduct() {
  await createProductWithImage();
}


function openImageUploadModal(pid, pname) {
  openModal(`
    <h3>Telecharger une image pour "${html(pname)}"</h3>
    <form id="imgForm" onsubmit="event.preventDefault(); uploadProductImage(${pid});">
      <input type="file" id="imgFile" accept="image/png,image/jpeg,image/gif,image/webp" required>
      <div style="font-size:0.8rem;color:var(--muted);margin:0.5rem 0;">Formats: PNG, JPG, GIF, WebP. Max 5 Mo.</div>
      <div style="display:flex;gap:0.5rem;">
        <button type="submit" class="btn">Telecharger</button>
        <button type="button" class="btn secondary" onclick="closeModal()">Annuler</button>
      </div>
    </form>
    <div id="imgMsg"></div>
  `);
}

async function uploadProductImage(pid) {
  const fileInput = $("#imgFile");
  if (!fileInput.files || !fileInput.files[0]) {
    $("#imgMsg").innerHTML = `<p class="error">Veuillez choisir une image.</p>`;
    return;
  }
  const file = fileInput.files[0];
  if (file.size > 5 * 1024 * 1024) {
    $("#imgMsg").innerHTML = `<p class="error">Image trop lourde (max 5 Mo).</p>`;
    return;
  }
  const formData = new FormData();
  formData.append("image", file);
  try {
    const res = await fetch(API + `/api/v1/merchant/products/${pid}/image`, {
      method: "POST",
      body: formData,
      credentials: "same-origin"
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Erreur upload");
    const previewUrl = data.image_url ? `${data.image_url}?t=${Date.now()}` : "";
    $("#imgMsg").innerHTML = `<p class="success">Image televersee !
      ${previewUrl ? `<img src="${html(previewUrl)}" alt="aperçu" style="max-width:120px;border-radius:8px;display:block;margin-top:0.5rem;">` : ""}
    </p>`;
    state.products = []; // force refresh catalogue client
    setTimeout(() => { closeModal(); supplierTab("products"); }, 1200);
  } catch (e) {
    $("#imgMsg").innerHTML = `<p class="error">${e.message}</p>`;
  }
}

async function openProductModal(pid) {
  const cats = await api("/api/categories");
  const prods = await api("/api/supplier/products");
  const p = prods.find(x => x.id === pid);
  if (!p) return;
  openModal(`
    <h3>Modifier le produit</h3>
    <label>Nom</label><input id="epname" value="${html(p.name)}">
    <label>Description</label><textarea id="epdesc">${html(p.description)}</textarea>
    <div class="form-row">
      <div><label>Prix</label><input id="epprice" type="number" value="${p.price}"></div>
      <div><label>Stock</label><input id="epstock" type="number" value="${p.stock}"></div>
    </div>
    <label>Categorie</label>
    <select id="epcat">${cats.map(c => `<option value="${c.id}" ${p.category_id == c.id ? 'selected' : ''}>${html(c.name)}</option>`).join("")}</select>
    <label><input id="epfragile" type="checkbox" ${p.fragile ? 'checked' : ''}> Produit fragile</label>
    <label>Image actuelle</label>
    <img src="${p.image_url || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22%3E%3Crect width=%22100%25%22 height=%22100%25%22 fill=%22%23eef2f7%22/%3E%3C/svg%3E'}" style="max-width:120px;border-radius:8px;display:block;margin-bottom:0.75rem;">
    <label>Remplacer l'image</label>
    <input type="file" id="epimageFile" accept="image/png,image/jpeg,image/gif,image/webp">
    <div style="font-size:0.8rem;color:var(--muted);margin-bottom:0.75rem;">Formats: PNG, JPG, GIF, WebP. Max 5 Mo.</div>
    <label>Ou URL image externe</label><input id="epimage" value="${html(p.image_url || '')}">
    <label><input id="epactive" type="checkbox" ${p.active ? 'checked' : ''}> Actif</label>
    <div style="display:flex;gap:0.5rem;margin-top:1rem;">
      <button class="btn" onclick="updateProduct(${p.id})">Enregistrer</button>
      <button class="btn secondary" onclick="closeModal()">Annuler</button>
    </div>
    <div id="epmsg"></div>
  `);
}

async function updateProduct(pid) {
  try {
    await api(`/api/supplier/products/${pid}`, { method: "PUT", body: {
      name: $("#epname").value, description: $("#epdesc").value,
      price: parseFloat($("#epprice").value) || 0, stock: parseInt($("#epstock").value) || 0,
      category_id: parseInt($("#epcat").value), fragile: $("#epfragile").checked,
      image_url: $("#epimage").value || null, active: $("#epactive").checked
    }});
    
    // Upload new image if selected
    const fileInput = $("#epimageFile");
    if (fileInput.files && fileInput.files[0]) {
      const file = fileInput.files[0];
      if (file.size > 5 * 1024 * 1024) throw new Error("Image trop lourde (max 5 Mo)");
      const formData = new FormData();
      formData.append("image", file);
      const res = await fetch(API + `/api/v1/merchant/products/${pid}/image`, {
        method: "POST", body: formData, credentials: "same-origin"
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Erreur upload image");
      }
    }
    
    state.products = [];
    closeModal();
    supplierTab("products");
  } catch (e) { $("#epmsg").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function deleteProduct(pid) {
  if (!confirm("Supprimer ce produit ?")) return;
  await api(`/api/supplier/products/${pid}`, { method: "DELETE" });
  state.products = [];
  supplierTab("products");
}

async function renderLivreur(app) {
  app.innerHTML = `<div class="card"><h2>Espace Livreur</h2>
    <div id="livreur-tabs" class="tabs">
      <div class="tab active" data-tab="available" onclick="livreurTab('available')">Commandes dispo</div>
      <div class="tab" data-tab="missions" onclick="livreurTab('missions')">Mes missions</div>
      <div class="tab" data-tab="wallet" onclick="livreurTab('wallet')">Portefeuille</div>
      <div class="tab" data-tab="map" onclick="livreurTab('map')">Carte / Geolocalisation</div>
    </div>
    <div id="liv-content"></div>
  </div>`;
  livreurTab("available");
}

async function livreurTab(tab) {
  document.querySelectorAll("#livreur-tabs .tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
  const content = $("#liv-content");
  if (tab === "available") {
    content.innerHTML = "Chargement...";
    try {
      const orders = await api("/api/livreur/available-orders");
      content.innerHTML = `
        <p style="color:var(--muted);font-size:0.9rem;margin-bottom:0.75rem;">
          Commandes en livraison sans livreur. Cliquez sur <strong>Prendre la mission</strong> pour vous l'attribuer.
        </p>
        ${orders.map(o => `
          <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
              <strong>${html(o.code)}</strong>
              <span class="status ${o.status}">${html(o.status)}</span>
            </div>
            <p>Fournisseur: ${html(o.supplier_name)} — ${html(o.supplier_phone || "")}</p>
            <p>Livraison: ${html(o.delivery_address || "—")}</p>
            <p>Total: ${money(o.total)} (frais livr. ${money(o.delivery_fee)})${o.is_fragile ? ' — <span class="tag" style="background:#fee2e2;color:var(--danger);">Fragile</span>' : ""}</p>
            <p style="font-size:0.85rem;color:var(--muted);">${o.created_at ? new Date(o.created_at).toLocaleString() : ""}</p>
            <button type="button" class="btn" onclick="claimOrderAsLivreur(${o.id})">Prendre la mission</button>
          </div>
        `).join("") || "<p>Aucune commande disponible pour le moment.</p>"}
      `;
    } catch (e) {
      content.innerHTML = `<p class="error">${html(e.message)}</p>`;
    }
  } else if (tab === "missions") {
    content.innerHTML = "Chargement...";
    const missions = await api("/api/livreur/missions");
    const steps = ["ACCEPTED", "STARTED", "PICKUP_INITIATED", "PICKED_UP", "IN_TRANSIT", "DELIVERED"];
    const stepLabels = {
      ACCEPTED: "1. Acceptee",
      STARTED: "2. Demarree",
      PICKUP_INITIATED: "3. Recuperation",
      PICKED_UP: "4. Colis recu",
      IN_TRANSIT: "5. Vers client",
      DELIVERED: "6. Livree"
    };
    content.innerHTML = `
      <p style="color:var(--muted);font-size:0.9rem;margin-bottom:0.75rem;">
        <strong>Demarrer</strong> (Oui/Non) → chez le fournisseur <strong>Initialiser recuperation</strong> →
        <strong>Colis recu</strong> (livreur ou client) → en route client → livrer.
      </p>
      ${missions.map(m => {
        const idx = steps.indexOf(m.status);
        const progress = steps.map((s, i) => {
          const done = idx >= i || m.status === "DELIVERED";
          const current = m.status === s;
          return `<span class="tag" style="${current ? "background:var(--primary);color:#fff;" : done && idx > i ? "background:#d1fae5;color:#047857;" : ""}">${stepLabels[s]}</span>`;
        }).join(" ");
        let actions = "";
        if (m.can_start) {
          actions = `<button type="button" class="btn" onclick="missionAction(${m.id}, 'start')">▶ Demarrer la course</button>`;
        } else if (m.can_init_pickup) {
          actions = `<button type="button" class="btn" onclick="missionAction(${m.id}, 'init_pickup')">📦 Initialiser la recuperation du colis</button>`;
        } else if (m.can_confirm_received && m.status === "PICKUP_INITIATED") {
          actions = `<button type="button" class="btn ok" onclick="missionAction(${m.id}, 'confirm_received')">✅ Colis recu</button>
            <p style="font-size:0.8rem;color:var(--muted);width:100%;">Le client peut aussi cliquer « Colis recu » sur sa commande.</p>`;
        } else if (m.can_en_route) {
          actions = `<button type="button" class="btn" onclick="missionAction(${m.id}, 'en_route')">🛵 En route vers le client</button>`;
        } else if (m.can_confirm_cod_payment || m.needs_cod_payment) {
          actions = `
            <div class="card" style="background:#fff7ed;border:1px solid #fed7aa;margin:0;padding:0.75rem;width:100%;">
              <strong>💵 Paiement a la livraison</strong>
              <p style="font-size:0.85rem;margin:0.35rem 0;">
                Montant a encaisser: <strong>${money(m.order_total || m.price)}</strong>
                — statut: <span class="tag">${html(m.payment_status || "pending")}</span>
              </p>
              <p style="font-size:0.85rem;color:var(--muted);margin:0 0 0.5rem;">
                Encaissez le client, puis confirmez le paiement. Ensuite seulement vous pourrez saisir l'OTP et terminer.
              </p>
              <button type="button" class="btn" onclick="missionAction(${m.id}, 'confirm_cod_payment')">
                💵 Paiement recu du client
              </button>
            </div>
          `;
        } else if (m.can_deliver && m.status === "IN_TRANSIT") {
          actions = `
            <div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;">
              <input id="otp_${m.id}" placeholder="OTP client" style="margin-bottom:0;max-width:140px;" value="${html(m.otp_code || "")}">
              <button type="button" class="btn ok" onclick="missionAction(${m.id}, 'deliver')">✅ Confirmer livraison</button>
            </div>
            <p style="font-size:0.8rem;color:var(--muted);margin-top:0.35rem;">
              ${m.payment_method === "cash_on_delivery" ? "Paiement COD confirme. " : ""}Demandez l'OTP au client puis validez.
            </p>
          `;
        } else if (m.status === "DELIVERED") {
          actions = `<p class="success">Livraison terminee${m.delivery_time ? " — " + new Date(m.delivery_time).toLocaleString() : ""}.</p>`;
        } else if (m.status === "CANCELLED") {
          actions = `<p class="error">Course annulee.</p>`;
        }
        if (!["DELIVERED", "CANCELLED"].includes(m.status)) {
          actions += ` <button type="button" class="btn small danger" onclick="missionAction(${m.id}, 'cancel')">Annuler</button>`;
        }
        return `
          <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
              <strong>Course #${m.id} ${m.order_code ? "— " + html(m.order_code) : ""}</strong>
              <span class="status ${m.status}">${html(m.status_label || m.status)}</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:0.35rem;margin:0.5rem 0;">${progress}</div>
            <p><strong>Fournisseur (retrait):</strong> ${html(m.supplier_name || "—")}${m.supplier_phone ? ` — <a href="tel:${html(m.supplier_phone)}">${html(m.supplier_phone)}</a>` : ""}</p>
            <p><strong>Adresse retrait:</strong> ${html(m.pickup_address || "—")}</p>
            <div class="card" style="background:#f0f9ff;border:1px solid #bae6fd;margin:0.75rem 0;padding:0.75rem;">
              <div style="font-weight:700;margin-bottom:0.35rem;">📍 Coordonnees du destinataire</div>
              <p style="margin:0.25rem 0;"><strong>Nom :</strong> ${html(m.recipient_name || m.client_name || "—")}</p>
              <p style="margin:0.25rem 0;"><strong>Adresse de livraison :</strong> ${html(m.delivery_address || m.dropoff_address || "—")}</p>
              <p style="margin:0.25rem 0;"><strong>Telephone destinataire :</strong>
                ${(m.recipient_phone || m.contact_phone || m.client_phone)
                  ? `<a href="tel:${html(m.recipient_phone || m.contact_phone || m.client_phone)}" style="font-size:1.05rem;font-weight:700;">${html(m.recipient_phone || m.contact_phone || m.client_phone)}</a>`
                  : "—"}
              </p>
              ${(m.recipient_phone || m.contact_phone || m.client_phone) ? `
                <a class="btn" href="tel:${html(m.recipient_phone || m.contact_phone || m.client_phone)}" style="margin-top:0.5rem;display:inline-flex;align-items:center;gap:0.35rem;text-decoration:none;">
                  📞 Appeler le destinataire
                </a>
              ` : `<p class="error" style="margin-top:0.5rem;">Aucun telephone disponible.</p>`}
              <p style="font-size:0.8rem;color:var(--muted);margin:0.5rem 0 0;">Appelez le destinataire une fois arrive sur le lieu de livraison.</p>
            </div>
            <p>${money(m.price)} / ${m.distance_km} km
              ${m.is_fragile ? ' — <span class="tag" style="background:#fee2e2;color:var(--danger);">Fragile</span>' : ""}
            </p>
            <p>OTP course: <code>${html(m.otp_code || "—")}</code></p>
            <div style="margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;">
              ${actions}
              ${m.pickup_lat != null && m.dropoff_lat != null ? `<button type="button" class="btn small secondary" onclick="showMissionMap(${m.id}, ${m.pickup_lat}, ${m.pickup_lon}, ${m.dropoff_lat}, ${m.dropoff_lon})">Voir trajet</button>` : ""}
            </div>
            <div id="mission-map-${m.id}" class="hidden" style="height:220px;margin-top:0.75rem;border-radius:8px;border:1px solid var(--border);"></div>
          </div>
        `;
      }).join("") || "<p>Aucune mission. Prenez-en une dans l'onglet Commandes dispo.</p>"}
    `;
  } else if (tab === "wallet") {
    content.innerHTML = "Chargement du portefeuille...";
    try {
      await renderLivreurWallet(content);
    } catch (e) {
      content.innerHTML = `<p class="error">${html(e.message)}</p>`;
    }
  } else if (tab === "map") {
    content.innerHTML = `
      <div class="card">
        <p>Activez la geolocalisation pour envoyer votre position en temps reel.</p>
        <button class="btn" type="button" onclick="startLivreurTracking()">Activer le suivi</button>
        <button class="btn secondary" type="button" onclick="sendLocationOnce()">Envoyer position actuelle</button>
        <div id="map" style="margin-top:1rem;"></div>
      </div>
    `;
    setTimeout(() => initMap("map", 6.1725, 1.2253), 100);
  }
}

async function renderLivreurWallet(content) {
  const wallet = await api("/api/wallet");
  const history = wallet.history || [];
  content.innerHTML = `
    <h3 style="margin-top:0;">Portefeuille — frais de livraison</h3>
    <p style="color:var(--muted);font-size:0.9rem;">
      Ici apparaissent <strong>uniquement vos frais de course</strong> (pas le prix des produits du fournisseur).
    </p>
    <div class="grid grid-2" style="gap:0.75rem;margin-bottom:1rem;">
      <div class="card" style="margin:0;padding:1rem;background:#ecfdf5;border:1px solid #a7f3d0;">
        <div style="font-size:0.85rem;color:var(--muted);">Solde retirable</div>
        <div style="font-size:1.5rem;font-weight:800;color:#047857;">${money(wallet.available || 0)}</div>
        <button type="button" class="btn" style="margin-top:0.75rem;" id="btnLivreurWithdraw">
          Initialiser un retrait
        </button>
      </div>
      <div class="card" style="margin:0;padding:1rem;background:#eff6ff;border:1px solid #bfdbfe;">
        <div style="font-size:0.85rem;color:var(--muted);">Gains frais cumules</div>
        <div style="font-size:1.25rem;font-weight:800;">${money(wallet.earned || 0)}</div>
        <div style="font-size:0.85rem;color:var(--muted);margin-top:0.35rem;">Deja retire: ${money(wallet.withdrawn || 0)}</div>
      </div>
    </div>
    <div id="walletMsg"></div>
    <h3>Historique des retraits</h3>
    ${history.length ? `
      <div style="overflow-x:auto;">
        <table class="sales-table">
          <thead><tr><th>Date</th><th>Type</th><th>Statut</th><th style="text-align:right;">Montant</th></tr></thead>
          <tbody>
            ${history.map(h => `
              <tr>
                <td>${h.created_at ? new Date(h.created_at).toLocaleString() : "—"}</td>
                <td>${html(h.kind || "—")}</td>
                <td>${html(h.status || "—")}</td>
                <td style="text-align:right;font-weight:700;">${money(h.amount)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    ` : "<p>Aucun retrait pour le moment.</p>"}
  `;
  const btn = $("#btnLivreurWithdraw");
  if (btn) {
    btn.onclick = () => initWalletWithdraw("livreur");
  }
}

async function updateMissionStatus(mid) {
  try {
    const sel = $(`#ms_${mid}`);
    await api(`/api/livreur/missions/${mid}/status`, {
      method: "POST",
      body: { status: sel ? sel.value : "ACCEPTED" }
    });
    livreurTab("missions");
  } catch (e) { alert(e.message); }
}

const MISSION_CONFIRMS = {
  start: "Etes-vous sur de demarrer la course ?",
  init_pickup: "Initialiser la recuperation du colis chez le fournisseur ?",
  confirm_received: "Confirmer que le colis a bien ete recu ?",
  pickup: "Confirmer que le colis a bien ete recu ?",
  en_route: "Etes-vous sur de partir vers le client ?",
  confirm_cod_payment: "Confirmer que le client a bien paye le montant a la livraison ?",
  deliver: "Confirmer la livraison au client ?",
  cancel: "Annuler cette course ?"
};

async function missionAction(runId, action) {
  try {
    const question = MISSION_CONFIRMS[action] || "Confirmer cette action ?";
    if (!confirm(question + "\n\nOK = Oui  |  Annuler = Non")) return;

    const body = { action };
    if (action === "deliver") {
      const otpEl = $(`#otp_${runId}`);
      const otp = otpEl ? otpEl.value.trim() : "";
      if (!otp) { alert("Saisissez l'OTP du client pour confirmer la livraison."); return; }
      body.otp = otp;
    }
    const res = await api(`/api/livreur/missions/${runId}/action`, { method: "POST", body });
    if (res.message) alert(res.message);
    if (action === "start") {
      try { sendLocationOnce(); } catch (_) {}
    }
    livreurTab("missions");
  } catch (e) { alert(e.message); }
}

async function orderPickupAction(orderId, action) {
  try {
    const q = action === "init_pickup"
      ? "Initialiser la recuperation du colis chez le fournisseur ?\n\nOK = Oui  |  Annuler = Non"
      : "Confirmer que le colis a bien ete recu ?\n\nOK = Oui  |  Annuler = Non";
    if (!confirm(q)) return;
    const res = await api(`/api/orders/${orderId}/pickup-action`, {
      method: "POST",
      body: { action }
    });
    if (res.message) alert(res.message);
    go("order", { id: orderId });
  } catch (e) { alert(e.message); }
}

function showMissionMap(runId, plat, plon, dlat, dlon) {
  const el = $(`#mission-map-${runId}`);
  if (!el) return;
  el.classList.remove("hidden");
  initMap(`mission-map-${runId}`, plat, plon, dlat, dlon);
}

function startLivreurTracking() {
  if (!navigator.geolocation) { alert("Geolocalisation non supportee"); return; }
  navigator.geolocation.watchPosition(async pos => {
    await api("/api/livreur/location", { method: "POST", body: { lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy: pos.coords.accuracy } });
    if (mapInstance) {
      mapInstance.setView([pos.coords.latitude, pos.coords.longitude], 15);
      L.marker([pos.coords.latitude, pos.coords.longitude]).addTo(mapInstance).bindPopup("Ma position").openPopup();
    }
  }, err => alert("Erreur GPS: " + err.message), { enableHighAccuracy: true });
  alert("Suivi active. Votre position est envoyee toutes les quelques secondes.");
}

function sendLocationOnce() {
  if (!navigator.geolocation) { alert("Geolocalisation non supportee"); return; }
  navigator.geolocation.getCurrentPosition(async pos => {
    await api("/api/livreur/location", { method: "POST", body: { lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy: pos.coords.accuracy } });
    if (mapInstance) {
      mapInstance.setView([pos.coords.latitude, pos.coords.longitude], 15);
      L.marker([pos.coords.latitude, pos.coords.longitude]).addTo(mapInstance).bindPopup("Position actuelle").openPopup();
    }
    alert("Position envoyee");
  }, err => alert("Erreur GPS: " + err.message));
}

function initMap(containerId, lat1, lon1, lat2, lon2) {
  const el = $("#" + containerId);
  if (!el || typeof L === 'undefined') return;
  el.innerHTML = "";
  const center = lat2 ? [(lat1 + lat2) / 2, (lon1 + lon2) / 2] : [lat1, lon1];
  const zoom = lat2 ? 13 : 14;
  const map = L.map(el).setView(center, zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap' }).addTo(map);
  if (lat2 !== undefined) {
    L.marker([lat1, lon1]).addTo(map).bindPopup("Enlevement");
    L.marker([lat2, lon2]).addTo(map).bindPopup("Livraison");
    L.polyline([[lat1, lon1], [lat2, lon2]], { color: 'var(--primary)' }).addTo(map);
  } else {
    L.marker([lat1, lon1]).addTo(map).bindPopup("Position");
  }
  mapInstance = map;
}

async function renderAdmin(app) {
  app.innerHTML = `<div class="card"><h2>Administration</h2>
    <div id="admin-tabs" class="tabs">
      <div class="tab active" data-tab="dashboard" onclick="adminTab('dashboard')">Tableau de bord</div>
      <div class="tab" data-tab="dispatch" onclick="adminTab('dispatch')">Attribution livreurs</div>
      <div class="tab" data-tab="pending" onclick="adminTab('pending')">Validations KYC</div>
      <div class="tab" data-tab="audit" onclick="adminTab('audit')">Journal</div>
      <div class="tab" data-tab="notif" onclick="adminTab('notif')">Notifications test</div>
    </div>
    <div id="admin-content"></div>
  </div>`;
  adminTab("dashboard");
}

async function adminTab(tab) {
  document.querySelectorAll("#admin-tabs .tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
  const content = $("#admin-content");
  if (tab === "dashboard") {
    content.innerHTML = "Chargement...";
    const stats = await api("/api/admin/stats");
    const analytics = await api("/api/admin/analytics");
    content.innerHTML = `
      <div class="grid grid-4">
        <div class="card"><strong>Utilisateurs</strong><div class="price">${stats.users}</div></div>
        <div class="card"><strong>Commandes</strong><div class="price">${stats.orders}</div></div>
        <div class="card"><strong>Revenus</strong><div class="price">${money(stats.total_revenue)}</div></div>
        <div class="card"><strong>En attente</strong><div class="price">${stats.pending_validation}</div></div>
      </div>
      <div class="card"><h3>Commandes par jour (14 jours)</h3>
        <div class="chart-container"><canvas id="ordersChart"></canvas></div>
      </div>
      <div class="grid grid-2">
        <div class="card"><h3>Statuts des commandes</h3><div class="chart-container"><canvas id="statusChart"></canvas></div></div>
        <div class="card"><h3>Top fournisseurs</h3>
          <table><thead><tr><th>Fournisseur</th><th>Commandes</th><th>Revenus</th></tr></thead><tbody>
          ${analytics.top_suppliers.map(s => `<tr><td>${html(s.name)}</td><td>${s.orders}</td><td>${money(s.revenue)}</td></tr>`).join("")}
          </tbody></table>
        </div>
      </div>
    `;
    setTimeout(() => drawAdminCharts(analytics), 100);
  } else if (tab === "dispatch") {
    content.innerHTML = "Chargement...";
    try {
      const [orders, livreurs] = await Promise.all([
        api("/api/admin/orders"),
        api("/api/livreurs")
      ]);
      const deliveryOrders = orders.filter(o => o.mode === "delivery" && !["CANCELLED", "FAILED"].includes(o.status));
      const unassigned = deliveryOrders.filter(o => !o.assigned && o.status !== "DELIVERED");
      const assigned = deliveryOrders.filter(o => o.assigned);
      const livreurOptions = livreurs.length
        ? livreurs.map(l => `<option value="${l.id}">${html([l.first_name, l.last_name].filter(Boolean).join(" ") || l.phone)} ★${(l.average_rating || 0).toFixed(1)} (${l.total_deliveries || 0} livr.)</option>`).join("")
        : `<option value="">Aucun livreur</option>`;

      content.innerHTML = `
        <h3>Attribution des livreurs</h3>
        <p style="color:var(--muted);font-size:0.9rem;">Assignez un livreur a une commande, ou laissez le livreur se l'attribuer lui-meme.</p>
        <h4 style="margin-top:1rem;">A attribuer (${unassigned.length})</h4>
        ${unassigned.map(o => `
          <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
              <strong>${html(o.code)}</strong>
              <span class="status ${o.status}">${html(o.status)}</span>
            </div>
            <p>Fournisseur: ${html(o.supplier_name)} — Client: ${html(o.client_phone || "—")}</p>
            <p>Adresse: ${html(o.delivery_address || "—")}</p>
            <p>Total: ${money(o.total)}</p>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-top:0.5rem;">
              <select id="liv_adm_${o.id}" style="margin-bottom:0;min-width:180px;">${livreurOptions}</select>
              <button type="button" class="btn small" onclick="assignLivreur(${o.id}, 'liv_adm_${o.id}')">Attribuer</button>
            </div>
          </div>
        `).join("") || "<p>Toutes les livraisons ont un livreur.</p>"}
        <h4 style="margin-top:1.5rem;">Deja assignees (${assigned.length})</h4>
        ${assigned.slice(0, 30).map(o => `
          <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
              <strong>${html(o.code)}</strong>
              <span class="status ${o.status}">${html(o.status)}</span>
            </div>
            <p>Livreur: <strong>${html(o.assigned_livreur_name || ("#" + o.assigned_livreur_id))}</strong></p>
            <p>Fournisseur: ${html(o.supplier_name)} — ${money(o.total)}</p>
          </div>
        `).join("") || "<p>Aucune.</p>"}
      `;
    } catch (e) {
      content.innerHTML = `<p class="error">${html(e.message)}</p>`;
    }
  } else if (tab === "pending") {
    content.innerHTML = "Chargement...";
    const pending = await api("/api/admin/pending-users");
    if (!pending.length) { content.innerHTML = `<h3>Validations KYC en attente</h3><p>Aucune.</p>`; return; }
    const details = await Promise.all(pending.map(u => api(`/api/admin/users/${u.id}/kyc`).catch(() => ({}))));
    content.innerHTML = `<h3>Validations KYC en attente</h3>` + pending.map((u, idx) => {
      const kyc = details[idx] || {};
      return `
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;">
            <div>
              <strong>${html(u.company_name || u.first_name || "—")}</strong> — ${u.role} — ${u.phone}
              <div style="font-size:0.85rem;color:var(--muted);">
                ${kyc.id_document ? `<a href="${kyc.id_document}" target="_blank">Voir piece d'identite</a>` : 'Piece d\'identite manquante'}
                ${kyc.cfe_document ? ` | <a href="${kyc.cfe_document}" target="_blank">Voir CFE</a>` : ''}
              </div>
            </div>
            <button class="btn small" onclick="validateUser(${u.id})">Valider le compte</button>
          </div>
        </div>
      `;
    }).join("");
  } else if (tab === "audit") {
    content.innerHTML = "Chargement...";
    const logs = await api("/api/admin/audit-logs");
    content.innerHTML = `<h3>Journal d'audit (200 derniers)</h3>
      <div style="overflow-x:auto;">
      <table><thead><tr><th>Date</th><th>Acteur</th><th>Role</th><th>Action</th><th>Cible</th><th>IP</th></tr></thead><tbody>
      ${logs.map(l => `<tr><td>${new Date(l.created_at).toLocaleString()}</td><td>${l.actor_id || '—'}</td><td>${l.actor_role || '—'}</td><td>${html(l.action)}</td><td>${html(l.target_type || '')} #${l.target_id || '—'}</td><td>${l.ip || '—'}</td></tr>`).join("")}
      </tbody></table></div>`;
  } else if (tab === "notif") {
    content.innerHTML = `
      <h3>Envoyer une notification test</h3>
      <label>Canal</label>
      <select id="nchannel"><option value="in-app">In-app</option><option value="sms">SMS (simule)</option><option value="whatsapp">WhatsApp (simule)</option></select>
      <label>ID utilisateur</label><input id="nuser" type="number" placeholder="laisse vide pour envoyer a tous">
      <label>Titre</label><input id="ntitle" value="Notification test">
      <label>Message</label><textarea id="nbody">Ceci est un message test.</textarea>
      <button class="btn" onclick="sendTestNotif()">Envoyer</button>
      <div id="nmsg"></div>
    `;
  }
}

function drawAdminCharts(analytics) {
  if (typeof Chart === 'undefined') return;
  const ctx1 = $("#ordersChart");
  if (ctx1) {
    new Chart(ctx1, {
      type: 'line',
      data: {
        labels: analytics.orders_by_day.map(d => d.day),
        datasets: [{
          label: 'Commandes',
          data: analytics.orders_by_day.map(d => d.count),
          borderColor: '#0b5fff', backgroundColor: 'rgba(11,95,255,0.1)', fill: true, tension: 0.3
        }, {
          label: 'Revenus (XOF / 1000)',
          data: analytics.orders_by_day.map(d => (d.total / 1000).toFixed(1)),
          borderColor: '#0d9488', backgroundColor: 'rgba(13,148,136,0.1)', fill: true, tension: 0.3
        }]
      },
      options: { responsive: true, maintainAspectRatio: false }
    });
  }
  const ctx2 = $("#statusChart");
  if (ctx2) {
    new Chart(ctx2, {
      type: 'doughnut',
      data: {
        labels: Object.keys(analytics.status_counts),
        datasets: [{ data: Object.values(analytics.status_counts), backgroundColor: ['#0b5fff','#b45309','#1e40af','#047857','#b91c1c','#94a3b8'] }]
      },
      options: { responsive: true, maintainAspectRatio: false }
    });
  }
}

async function validateUser(uid) {
  await api(`/api/admin/users/${uid}/validate`, { method: "POST" });
  adminTab("pending");
}

async function sendTestNotif() {
  try {
    const userId = $("#nuser").value ? parseInt($("#nuser").value) : null;
    await api("/api/notifications/send-test", { method: "POST", body: {
      user_id: userId, channel: $("#nchannel").value,
      title: $("#ntitle").value, body: $("#nbody").value
    }});
    $("#nmsg").innerHTML = `<p class="success">Notification envoyee.</p>`;
  } catch (e) { $("#nmsg").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function renderPayment(app, params) {
  const type = params.type || 'order';
  const id = parseInt(params.id);
  const amount = parseFloat(params.amount);
  app.innerHTML = `
    <div class="card" style="max-width:480px;margin:auto;">
      <h2>Paiement</h2>
      <p>Montant a payer: <span class="price">${money(amount)}</span></p>
      <label>Operateur / methode</label>
      <select id="provider">
        <option value="tmoney">Tmoney</option>
        <option value="flooz">Flooz</option>
        <option value="ecobank">Ecobank Express</option>
        <option value="cash">Paiement a la livraison</option>
      </select>
      <label>Numero de telephone / compte</label>
      <input id="payphone" value="${state.user ? state.user.phone : ''}" placeholder="+228 XX XX XX XX">
      <button class="btn" onclick="initiatePayment('${type}', ${id}, ${amount})">Demander le paiement</button>
      <div id="paymsg"></div>
      <div id="payconfirm" class="hidden" style="margin-top:1rem;">
        <p>En production, un code OTP ou une notification USSD serait envoye sur votre telephone. Ici, simulez la reponse :</p>
        <button class="btn ok" onclick="confirmPayment(true)">Simuler succes</button>
        <button class="btn secondary" onclick="confirmPayment(false)">Simuler echec</button>
      </div>
    </div>`;
}

let currentTxRef = null;

async function initiatePayment(type, id, amount) {
  try {
    const res = await api("/api/payments/initiate", { method: "POST", body: {
      target_type: type, target_id: id, provider: $("#provider").value, phone: $("#payphone").value
    }});
    currentTxRef = res.reference;
    $("#paymsg").innerHTML = `<p class="success">Transaction ${res.reference} initiee. Montant: ${money(res.amount)}</p>`;
    $("#payconfirm").classList.remove("hidden");
  } catch (e) { $("#paymsg").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function confirmPayment(success) {
  if (!currentTxRef) return;
  try {
    const res = await api(`/api/payments/${currentTxRef}/confirm`, { method: "POST", body: { simulate_success: success } });
    $("#paymsg").innerHTML = `<p class="${res.status === 'success' ? 'success' : 'error'}">Paiement ${res.status}${res.status === 'success' ? ' ✅' : ' ❌'}</p>`;
    $("#payconfirm").classList.add("hidden");
  } catch (e) { $("#paymsg").innerHTML = `<p class="error">${e.message}</p>`; }
}

// ---------- notifications panel ----------

function closeNotifPanel() {
  const panel = $("#notif-panel");
  if (panel) panel.classList.remove("open");
}

function toggleNotifPanel() {
  const panel = $("#notif-panel");
  if (!panel) return;
  panel.classList.toggle("open");
  if (panel.classList.contains("open")) refreshNotifications();
}

function normalizeNotifLink(link) {
  if (!link) return null;
  let raw = String(link).trim();
  if (!raw) return null;
  raw = raw.replace(/^#/, "").replace(/^\/+/, "");
  const [pagePart, query] = raw.split("?");
  const page = (pagePart || "").replace(/^\/+/, "") || "home";
  const params = {};
  if (query) new URLSearchParams(query).forEach((v, k) => { params[k] = v; });
  return { page, params };
}

async function refreshNotifications() {
  if (!state.user) return;
  try {
    const notes = await api("/api/notifications");
    const unread = notes.filter(n => !n.is_read).length;
    const badge = $("#notif-badge");
    if (badge) {
      badge.textContent = unread;
      badge.classList.toggle("hidden", unread === 0);
    }
    const list = $("#notif-list");
    if (list) {
      list.innerHTML = notes.length ? notes.map(n => `
        <div class="notif-item ${n.is_read ? "" : "unread"}" data-id="${n.id}" data-link="${html(n.link || "")}" role="button" tabindex="0">
          <strong>${html(n.title)} <span class="tag">${html(n.channel || "")}</span></strong>
          <span>${html(n.body || "")}</span>
          <small>${new Date(n.created_at).toLocaleString()}</small>
        </div>
      `).join("") : "<p>Aucune notification.</p>";
      list.querySelectorAll(".notif-item").forEach(el => {
        el.addEventListener("click", () => readNotif(el.dataset.id, el.dataset.link || ""));
        el.addEventListener("keydown", ev => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            readNotif(el.dataset.id, el.dataset.link || "");
          }
        });
      });
    }
  } catch (e) { console.error(e); }
}

async function readNotif(id, link) {
  // Close the notification bar immediately on click
  closeNotifPanel();
  try {
    if (id) await api(`/api/notifications/${id}/read`, { method: "POST" });
  } catch (e) { console.error(e); }
  await refreshNotifications();
  const target = normalizeNotifLink(link);
  if (target && target.page) {
    go(target.page, target.params);
  }
}

// Close notification panel when clicking outside
document.addEventListener("click", (e) => {
  const panel = $("#notif-panel");
  if (!panel || !panel.classList.contains("open")) return;
  if (panel.contains(e.target)) return;
  if (e.target.closest && e.target.closest(".notif-toggle")) return;
  closeNotifPanel();
});

// ---------- modal ----------

function openModal(content) {
  $("#modal-content").innerHTML = content;
  $("#modal").classList.add("open");
}

function closeModal() {
  $("#modal").classList.remove("open");
  $("#modal-content").innerHTML = "";
}

$("#modal").addEventListener("click", e => {
  if (e.target.id === "modal") closeModal();
});

// ---------- routing ----------

async function renderProfile(app) {
  if (!state.user) { go('login'); return; }
  app.innerHTML = `
    <div class="card" style="max-width:680px;margin:auto;">
      <h2>Mon profil</h2>
      <div id="profile-content">Chargement...</div>
    </div>`;
  try {
    const u = await api("/api/profile");
    const fullName = u.full_name || [u.first_name, u.last_name].filter(Boolean).join(" ") || u.phone;
    const initial = html(fullName.charAt(0).toUpperCase());
    const roleLabel = html(u.role.toUpperCase());
    const stats = u.stats || {};
    const delivered = u.total_deliveries ?? stats.delivered_count ?? 0;
    const balance = u.balance ?? 0;
    const rating = Number(u.average_rating || 0).toFixed(1);

    const wallet = u.wallet || {};
    const livreurDashboard = u.role === "livreur" ? `
      <div class="livreur-stats" style="margin-bottom:1.25rem;">
        <div class="grid grid-2" style="gap:0.75rem;">
          <div class="card" style="background:#ecfdf5;border:1px solid #a7f3d0;margin:0;padding:0.9rem;">
            <div style="font-size:0.8rem;color:var(--muted);">Solde frais de livraison</div>
            <div style="font-size:1.35rem;font-weight:800;color:#047857;">${money(wallet.available != null ? wallet.available : balance)}</div>
            <div style="font-size:0.75rem;color:var(--muted);margin-top:0.25rem;">Uniquement vos frais de course (pas le prix des produits)</div>
            <button type="button" class="btn small" style="margin-top:0.5rem;" onclick="initWalletWithdraw('livreur')">Initialiser un retrait</button>
          </div>
          <div class="card" style="background:#eff6ff;border:1px solid #bfdbfe;margin:0;padding:0.9rem;">
            <div style="font-size:0.8rem;color:var(--muted);">Courses effectuees</div>
            <div style="font-size:1.35rem;font-weight:800;color:#1d4ed8;">${delivered}</div>
            <div style="font-size:0.75rem;color:var(--muted);margin-top:0.25rem;">Note moyenne ★ ${rating}</div>
            <div style="font-size:0.75rem;color:var(--muted);">Gains frais cumules: ${money(wallet.earned != null ? wallet.earned : (stats.total_earnings || 0))}</div>
            <div style="font-size:0.75rem;color:var(--muted);">Deja retire: ${money(wallet.withdrawn || 0)}</div>
          </div>
        </div>
        <div id="walletMsg"></div>
        <div class="card" style="background:#f8fafc;margin:0.75rem 0 0;padding:0.9rem;">
          <div style="font-weight:700;margin-bottom:0.5rem;">Informations livreur</div>
          <div class="profile-info-grid">
            <div><span class="muted">Nom</span><strong>${html(fullName)}</strong></div>
            <div><span class="muted">Telephone</span><strong><a href="tel:${html(u.phone)}">${html(u.phone)}</a></strong></div>
            <div><span class="muted">Email</span><strong>${html(u.email || "—")}</strong></div>
            <div><span class="muted">Adresse</span><strong>${html(u.address || "—")}</strong></div>
            <div><span class="muted">Vehicule</span><strong>${html(u.vehicle_type || "—")}</strong></div>
            <div><span class="muted">Plaque</span><strong>${html(u.license_plate || "—")}</strong></div>
            <div><span class="muted">Missions en cours</span><strong>${stats.active_missions ?? 0}</strong></div>
            <div><span class="muted">Courses annulees</span><strong>${stats.cancelled_count ?? 0}</strong></div>
            <div><span class="muted">Statut compte</span><strong>${u.is_active ? "Actif" : "Inactif"}${u.validated_by_admin ? " · Valide" : " · En attente validation"}</strong></div>
          </div>
        </div>
      </div>
    ` : `
      <div style="text-align:center;margin-bottom:1.5rem;">
        <div style="width:80px;height:80px;border-radius:50%;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;font-size:2rem;margin:0 auto 0.5rem;">${initial}</div>
        <h3>${html(fullName)}</h3>
        <p style="color:var(--muted);">${roleLabel} — ${html(u.phone)}</p>
      </div>
    `;

    $("#profile-content").innerHTML = `
      ${livreurDashboard}
      ${u.role === "livreur" ? `
        <div style="text-align:center;margin-bottom:1.25rem;">
          <div style="width:72px;height:72px;border-radius:50%;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;font-size:1.75rem;margin:0 auto 0.5rem;">${initial}</div>
          <h3 style="margin:0;">${html(fullName)}</h3>
          <p style="color:var(--muted);margin:0.25rem 0 0;">${roleLabel} — ${html(u.phone)}</p>
        </div>
      ` : ""}
      <h3>Modifier mes informations</h3>
      <form id="profileForm" onsubmit="event.preventDefault(); updateProfile();">
        <div class="form-row">
          <div><label>Prénom</label><input id="pfirst" value="${html(u.first_name || '')}"></div>
          <div><label>Nom</label><input id="plast" value="${html(u.last_name || '')}"></div>
        </div>
        <label>Email</label><input id="pemail" type="email" value="${html(u.email || '')}">
        <label>Téléphone</label>
        <input id="pphone" type="tel" value="${html(u.phone || '')}" placeholder="+228 XX XX XX XX" autocomplete="tel">
        <p style="font-size:0.85rem;color:var(--muted);margin:0.35rem 0 0.75rem;">
          Vous pouvez changer votre numero a tout moment. Il servira pour la connexion.
        </p>
        <label>Adresse</label><textarea id="paddress">${html(u.address || '')}</textarea>
        ${u.role === 'fournisseur' || u.role === 'societe' ? `
          <label>Nom de la société</label>
          <input id="pcompany" value="${html(u.company_name || '')}" placeholder="${u.role === 'societe' ? 'Ex. Express Fleet TG' : 'Ex. Restaurant Le Palmier'}" maxlength="120">
          <p style="font-size:0.85rem;color:var(--muted);margin:0.35rem 0 0.75rem;">
            ${u.role === 'societe'
              ? "Ce nom est visible par les clients quand ils choisissent une societe de livraison."
              : "Ce nom d'entreprise s'affiche en bas de chacun de vos plats dans le catalogue client."}
          </p>
        ` : ''}
        ${u.role === 'client' ? `
          <label>Societe de livraison preferee</label>
          <select id="ppreferredSoc"><option value="">Chargement...</option></select>
          <p style="font-size:0.85rem;color:var(--muted);margin:0.35rem 0 0.75rem;">
            Utilisee par defaut au checkout (modifiable a chaque commande).
          </p>
        ` : ''}
        ${u.role === 'livreur' ? `
          <div class="form-row">
            <div><label>Type de véhicule</label><input id="pvehicle" value="${html(u.vehicle_type || '')}" placeholder="Moto, Velo..."></div>
            <div><label>Plaque</label><input id="plate" value="${html(u.license_plate || '')}" placeholder="TG-XXXX-XX"></div>
          </div>
        ` : ''}
        <div style="margin:1.25rem 0;padding:0.9rem;border:1px solid var(--border);border-radius:10px;background:#f8fafc;">
          <div id="pwdRequestBlock">
            <h3 style="margin:0 0 0.35rem;font-size:1rem;">Mot de passe</h3>
            <p style="font-size:0.85rem;color:var(--muted);margin:0 0 0.75rem;">
              Pour des raisons de securite, le formulaire de modification n'apparait qu'apres votre demande.
            </p>
            <button type="button" class="btn secondary" id="btnRequestPwdChange" onclick="showPasswordChangeForm()">
              Changer mon mot de passe
            </button>
          </div>
          <div id="pwdChangeBlock" class="hidden">
            <h3 style="margin:0 0 0.5rem;font-size:1rem;">Modifier le mot de passe</h3>
            <p style="font-size:0.85rem;color:var(--muted);margin:0 0 0.75rem;">
              Indiquez votre mot de passe actuel, puis le nouveau (min. 6 caracteres).
            </p>
            <label>Mot de passe actuel</label>
            <input id="pcurpwd" type="password" autocomplete="current-password" placeholder="••••••••">
            <div class="form-row">
              <div>
                <label>Nouveau mot de passe</label>
                <input id="pnewpwd" type="password" autocomplete="new-password" placeholder="Au moins 6 caracteres">
              </div>
              <div>
                <label>Confirmer</label>
                <input id="pnewpwd2" type="password" autocomplete="new-password" placeholder="Retaper le nouveau">
              </div>
            </div>
            <button type="button" class="btn small secondary" onclick="hidePasswordChangeForm()">Annuler</button>
          </div>
        </div>
        <button type="submit" class="btn">Enregistrer les modifications</button>
      </form>
      <div id="pmsg"></div>
      <div style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid var(--border);">
        <strong>Membre depuis :</strong> ${u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
      </div>
    `;
    if (u.role === "client") {
      try {
        const list = await api("/api/societes");
        const sel = $("#ppreferredSoc");
        if (sel) {
          const pref = u.preferred_societe_id != null ? String(u.preferred_societe_id) : "";
          sel.innerHTML = `<option value="">Aucune (boutique / plateforme)</option>` +
            (list || []).map(s =>
              `<option value="${s.id}" ${String(s.id) === pref ? "selected" : ""}>${html(s.company_name)}</option>`
            ).join("");
        }
      } catch (e) {
        const sel = $("#ppreferredSoc");
        if (sel) sel.innerHTML = `<option value="">Aucune (boutique / plateforme)</option>`;
      }
    }
  } catch (e) {
    $("#profile-content").innerHTML = `<p class="error">${e.message}</p>`;
  }
}

function showPasswordChangeForm() {
  const req = $("#pwdRequestBlock");
  const form = $("#pwdChangeBlock");
  if (req) req.classList.add("hidden");
  if (form) {
    form.classList.remove("hidden");
    const cur = $("#pcurpwd");
    if (cur) cur.focus();
  }
}

function hidePasswordChangeForm() {
  const req = $("#pwdRequestBlock");
  const form = $("#pwdChangeBlock");
  if (form) {
    form.classList.add("hidden");
    ["pcurpwd", "pnewpwd", "pnewpwd2"].forEach(id => {
      const el = $("#" + id);
      if (el) el.value = "";
    });
  }
  if (req) req.classList.remove("hidden");
}

window.showPasswordChangeForm = showPasswordChangeForm;
window.hidePasswordChangeForm = hidePasswordChangeForm;

async function updateProfile() {
  try {
    const phone = ($("#pphone") ? $("#pphone").value : "").trim();
    if (!phone) {
      $("#pmsg").innerHTML = `<p class="error">Le numero de telephone est requis.</p>`;
      return;
    }
    const body = {
      first_name: $("#pfirst").value,
      last_name: $("#plast").value,
      email: $("#pemail").value,
      phone,
      address: $("#paddress").value
    };
    if ($("#pcompany")) body.company_name = ($("#pcompany").value || "").trim();
    if ($("#pvehicle")) body.vehicle_type = $("#pvehicle").value;
    if ($("#plate")) body.license_plate = $("#plate").value;
    if ($("#ppreferredSoc")) {
      const v = $("#ppreferredSoc").value;
      body.preferred_societe_id = v ? parseInt(v, 10) : null;
    }

    const pwdPanel = $("#pwdChangeBlock");
    const pwdOpen = pwdPanel && !pwdPanel.classList.contains("hidden");
    const currentPwd = (pwdOpen && $("#pcurpwd")) ? $("#pcurpwd").value : "";
    const newPwd = (pwdOpen && $("#pnewpwd")) ? $("#pnewpwd").value : "";
    const newPwd2 = (pwdOpen && $("#pnewpwd2")) ? $("#pnewpwd2").value : "";
    const wantsPwdChange = pwdOpen && !!(currentPwd || newPwd || newPwd2);
    if (wantsPwdChange) {
      if (!currentPwd) {
        $("#pmsg").innerHTML = `<p class="error">Indiquez votre mot de passe actuel.</p>`;
        return;
      }
      if (!newPwd || newPwd.length < 6) {
        $("#pmsg").innerHTML = `<p class="error">Le nouveau mot de passe doit contenir au moins 6 caracteres.</p>`;
        return;
      }
      if (newPwd !== newPwd2) {
        $("#pmsg").innerHTML = `<p class="error">La confirmation du mot de passe ne correspond pas.</p>`;
        return;
      }
      body.current_password = currentPwd;
      body.new_password = newPwd;
      body.new_password_confirm = newPwd2;
    }

    const res = await api("/api/profile", { method: "PUT", body });
    state.user = res.user;
    // Refresh catalogue caches so the new company name appears under products
    state.products = [];
    state.suppliers = [];
    renderNav();
    const pwdOk = wantsPwdChange ? " Profil et mot de passe mis a jour." : " Profil mis à jour avec succès.";
    $("#pmsg").innerHTML = `<p class="success">${pwdOk}</p>`;
    setTimeout(() => renderProfile($("#app")), 1000);
  } catch (e) {
    $("#pmsg").innerHTML = `<p class="error">${e.message}</p>`;
  }
}


window.addEventListener("hashchange", () => {
  const h = parseHash();
  render(h.page, h.params);
});
(async function init() {
  await loadUser();
  const h = parseHash();
  render(h.page, h.params);
  setInterval(refreshNotifications, 30000);
})();

