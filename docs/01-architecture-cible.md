# 01 — Target Architecture (Odoo 19 Community)

Status: **validated** (analysis approved, decisions D1–D8 below).
Reference implementation: `../../main/` (Flask + SQLAlchemy + SQLite, PWA frontend).

---

## 1. Design principles

1. **Flask is the functional reference.** Behavior is ported, not redesigned.
2. **Odoo is the central business core.** All business logic lives in
   `likdelivery_core/services/` — API-agnostic Python services.
3. **Thin API layers.** `likdelivery_api_client|merchant|driver` contain no
   business logic: deserialize → authenticate → authorize → call service →
   serialize. Shared logic is never duplicated across the three APIs.
4. **Third-party ready.** External apps use the same services via
   `likdelivery_api_thirdparty` (API Keys / OAuth2 client-credentials), so
   first-party and third-party behavior is identical by construction.
5. **Odoo-native back-office.** Admin functions (KYC validation, dispatch,
   audit, dashboards) are Odoo views, not public REST endpoints.

## 2. Repository layout

```
delivery/
├── README.md
├── docs/
│   ├── 01-architecture-cible.md        ← this file
│   ├── 02-traceability-matrix.md       ← rules + endpoint mapping
│   └── 03-implementation-plan.md       ← sprints, migration, tests
├── odoo/                               ← Odoo 19 runtime config (odoo.conf, Docker)
├── addons/
│   ├── likdelivery_core/               ← business core (models + services + security)
│   ├── likdelivery_api_base/           ← shared API plumbing (no business logic)
│   ├── likdelivery_api_client/         ← /api/v1/client/*
│   ├── likdelivery_api_merchant/       ← /api/v1/merchant/*
│   ├── likdelivery_api_driver/         ← /api/v1/driver/*
│   ├── likdelivery_api_thirdparty/     ← API Keys + OAuth2 + webhooks
│   ├── likdelivery_migration/          ← one-shot ETL SQLite → PostgreSQL
│   └── likdelivery_brand/              ← PWA hosting, manifest, theming
├── frontend/                           ← existing PWA (copied from main/static)
├── docker-compose.yml                  ← odoo + postgres (+ nginx)
└── tests/                              ← cross-stack regression harness
```

## 3. Module details

### 3.1 `likdelivery_core` (depends: `base`, `mail`, `contacts`)

The single source of truth for business behavior.

- `models/` — 17 Odoo models (mapping in `02-traceability-matrix.md` §M).
  All transactional models get `company_id`; `likdelivery.order` and
  `likdelivery.delivery.run` inherit `mail.thread` for status tracking.
- `services/` — pure business logic, one file per domain:

| Service | Responsibility | Rules |
|---|---|---|
| `pricing.py` | haversine, fee calculation, night detection, estimate breakdown | LK-PRC |
| `availability.py` | opening hours, `open_now`, supplier availability reasons | LK-CAT, LK-HRS |
| `cart_service.py` | server cart, guest tokens, quantity semantics | LK-CRT |
| `checkout.py` | per-supplier split, stock capping, preview, multi-order creation | LK-CHK |
| `order_lifecycle.py` | order status changes, pickup actions, view permissions | LK-ORD |
| `mission_lifecycle.py` | run state machine, OTP/COD enforcement, side effects | LK-MSN |
| `assignment.py` | 3-pool dispatch (shop → société → platform), claim, admin override | LK-ASN, LK-CLM |
| `cancellation.py` | 80/20 penalty, refund transaction | LK-CAN |
| `wallet.py` | credit on delivery, snapshot (derived balance), withdrawal | LK-WAL |
| `payment_service.py` | `PaymentProvider` interface + simulator implementation | LK-PAY |
| `rating.py` | eligibility, average recompute | LK-RAT |
| `recommendation.py` | rating-based driver ranking | LK-REC |
| `fleet.py` | société fleet: internal/external drivers | LK-SOC |
| `kyc.py` | document upload, validation gate | LK-KYC |
| `notification.py` | in-app fan-out, sms/whatsapp stubs | LK-NOT |
| `audit.py` | audit log writes (36 actions) | LK-AUD |
| `geo.py` | driver location append/read | LK-GEO |

- `security/` — 5 groups (`group_lik_client`, `_fournisseur`, `_livreur`,
  `_societe`, `_admin`; all imply `base.group_user`) + record rules per model
  (anti-BOLA by construction, matrix in `02-traceability-matrix.md` §S).
- `demo/` — exact port of `seed.py`: 7 accounts, 5 categories, 6 products,
  opening hours, default 80% cancellation rule.

### 3.2 `likdelivery_api_base` (depends: `likdelivery_core`)

Shared plumbing used by all API modules:

- JSON envelope: success `{"ok": true, "data": …}` / error
  `{"ok": false, "code": "STABLE_CODE", "error": "…"}`.
- Error catalogue (`AUTH_INVALID`, `BOLA`, `OTP_INVALID`,
  `MISSION_TRANSITION_INVALID`, `WALLET_INSUFFICIENT`, `VALIDATION`,
  `NOT_FOUND`, `RATE_LIMITED`, `IDEMPOTENT_REPLAY`, …).
- Authentication: dual mode — JWT HS256 (access 1 h, refresh 30 d rotating,
  jti revocation) for API clients; Odoo session cookie for the PWA.
  Passwords stay pbkdf2:sha256 (Werkzeug) → migrated hashes keep working.
- `Idempotency-Key` header support (stored 24 h) on all POST endpoints.
- Rate limiting (defaults: 100 req/min auth endpoints per IP, 30/min order
  creation, 10/min rating).
- Serializers (`*_to_dict` ports) shared by the three namespaces so response
  shapes are identical.

### 3.3 `likdelivery_api_client` — `/api/v1/client/*`

Public catalog + client account flows: auth, profile, catalog, cart,
checkout, orders, courier requests, payments, rating, notifications.
Guest mode preserved (token cart, guest orders with `guest_phone`).

### 3.4 `likdelivery_api_merchant` — `/api/v1/merchant/*`

Both supply-side roles:
- `fournisseur`: products CRUD + image, opening hours, KYC, order processing,
  init-handover, shop drivers, sales history, wallet.
- `societe`: fleet management (internal/external), preferred orders,
  assignment. Mounted under `/api/v1/merchant/fleet/*` and
  `/api/v1/merchant/orders/*` (role-gated).

### 3.5 `likdelivery_api_driver` — `/api/v1/driver/*`

Available orders, claim, missions (status + action aliases), COD confirm,
OTP/QR delivery validation, location push/read, wallet, opening hours.

### 3.6 `likdelivery_api_thirdparty` (depends: `likdelivery_api_base`)

- `likdelivery.api.key` model: key id + hashed secret, bound to a technical
  partner, scopes (`catalog:read`, `orders:write`, `missions:write`, …),
  per-key rate limit, expiry, revocation.
- OAuth2 client-credentials flow (token endpoint) issuing the same JWTs as
  first-party clients — one auth pipeline.
- HMAC-signed outbound webhooks for order/mission events (v1.1; stubs in v1).

### 3.7 `likdelivery_migration`

One-shot ETL (details in `03-implementation-plan.md` §4): SQLite → Odoo ORM
import with preserved primary keys, entity-by-entity reconciliation report.

### 3.8 `likdelivery_brand`

Serves the existing PWA from Odoo (static assets, manifest, service worker),
backend theming. The PWA only changes its `api()` base path + JWT header.

## 4. Decisions

| ID | Decision | Rationale |
|---|---|---|
| D1 | Odoo **19 Community**, Docker `odoo:19.0` + PostgreSQL 16 | Per existing spec; free back-office, mature ORM |
| D2 | Modules prefixed `likdelivery_`, models `likdelivery.*` | Project naming directive |
| D3 | Three namespaces `/api/v1/{client,merchant,driver}` | Project naming directive; société **included in merchant** (validated) |
| D4 | `likdelivery.product`, **not** `product.product` | Avoids sale/purchase/stock chain coupling; keeps reference semantics |
| D5 | Users = `res.partner` (`_inherit`, `lik_role`) + `likdelivery.user` (`_inherits`) holding phone-login + password hash; `res.users` reserved for back-office | Matches single-table multi-role reference |
| D6 | Wallet balance = computed fields derived from delivered runs/orders minus withdrawals (never stored writes) | Reference recomputes on every read; eliminates divergence |
| D7 | Admin surface = Odoo back-office views, not public REST | No behavior lost (admin endpoints map to views); smaller attack surface |
| D8 | Payments: `PaymentProvider` interface + simulator in v1; real Tmoney/Flooz/Ecobank adapters + HMAC webhook in v1.x | Simulation behavior preserved; production path prepared |

## 5. Out of scope for v1

- WebSockets / live GPS push (polling as in reference; `bus.bus` in v1.1).
- Real PSP integrations (simulator preserved; adapters behind interface).
- Native mobile apps.
- Any behavior change listed in `02-traceability-matrix.md` §LK-SEC
  (known-risk items are ported as-is, documented, fixed only on explicit
  business decision).
