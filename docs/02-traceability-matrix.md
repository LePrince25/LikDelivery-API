# 02 — Traceability Matrix (Flask → Odoo)

This document is the **porting contract**. Every rule is numbered (`LK-xxx-nn`)
and must be implemented in `likdelivery_core` with identical behavior.
The Flask reference (`main/app.py`, 3,445 lines) is authoritative; per-line
traces exist in `main/docs/MIGRATION_ODOO.md` §5 (naming superseded, rules stand).

---

## §M — Model mapping (17 models)

| # | Flask table | Odoo model | Notes |
|---|---|---|---|
| M1 | `users` | `res.partner` (`_inherit`) + `likdelivery.user` (`_inherits`) | `lik_role`: client/fournisseur/livreur/societe/admin. Partner carries: phone (login, unique), names, address, lat/lon, `company_name`, KYC docs, `vehicle_type`, `license_plate`, `average_rating` (default 5.0), `total_deliveries`, `validated_by_admin`, `is_active`, `preferred_societe_id`, `employer_societe_id`. `likdelivery.user` carries password hash + JWT state. **No stored `balance`** (D6 — computed). |
| M2 | `categories` | `likdelivery.product.category` | name, icon |
| M3 | `supplier_products` | `likdelivery.product` | supplier_id→partner, category, name, description, price, stock, active, fragile, image; created/updated |
| M4 | `opening_hours` | `likdelivery.opening.hour` | user→partner, day_of_week 0–6 (Mon=0), open/close `Float` time (service converts; reference stores `Time`) |
| M5 | `supplier_livreurs` | `likdelivery.shop.driver` | supplier, livreur, is_active (soft delete), created_at |
| M6 | `societe_livreurs` | `likdelivery.fleet.driver` | societe, livreur, `origin` internal/external, is_active |
| M7 | `orders` | `likdelivery.order` (+`mail.thread`) | code CMD-XXXXXXXX, client/guest_phone, supplier, mode, status (7), delivery address/coords, fees/totals, payment method/status, is_fragile, `open_for_platform_claim`, `preferred_societe_id`, `supplier_wallet_credited`, otp_code, rating |
| M8 | `order_lines` | `likdelivery.order.line` | order, product, quantity, unit_price |
| M9 | `delivery_runs` | `likdelivery.delivery.run` (+`mail.thread`) | order (nullable), standalone flag, pickup/dropoff address+coords, distance_km, price, status (8), livreur, otp_code, qr_token, is_fragile, pickup/delivery times, rating; +`source` boutique/societe/plateforme/admin |
| M10 | `cart_sessions` | `likdelivery.cart.session` | client (nullable), session_token (64 hex), supplier, product, quantity |
| M11 | `courier_requests` | `likdelivery.courier.request` | code CRS-XXXXXXXX, client/guest, pickup/dropoff, distance, price, fragile, payment, status, livreur |
| M12 | `cancellation_rules` | `likdelivery.cancellation.rule` | min/max hours, penalty_percent (80.0), applies_to_paid/cash, active |
| M13 | `payment_transactions` | `likdelivery.payment.transaction` | reference PAY-XXXXXXXXXX, target (order/courier polymorphic), amount, provider, phone, status, provider_ref, failure_reason |
| M14 | `notifications` | `likdelivery.notification` + `mail.message` | user/guest_phone, channel in-app/sms/whatsapp, title, body, link, is_read |
| M15 | `livreur_locations` | `likdelivery.driver.location` | livreur, lat, lon, accuracy, recorded_at |
| M16 | `audit_logs` | `likdelivery.audit.log` + `mail.tracking.value` | actor, role, action (36 values), target, ip, details JSON |
| M17 | `wallet_withdrawals` | `likdelivery.wallet.withdrawal` | user, role, amount, kind product_sales/delivery_fees, status, note |

---

## §R — Business rule catalogue

### LK-AUT — Authentication & accounts
| Rule | Spec |
|---|---|
| LK-AUT-01 | Register: `phone`, `password`, `role` required. Allowed roles: client, fournisseur, livreur, societe (never admin). |
| LK-AUT-02 | `company_name` required for fournisseur/societe. |
| LK-AUT-03 | `validated_by_admin` = True for client/livreur; False for fournisseur/societe (KYC gate). |
| LK-AUT-04 | Phone unique; 409 on conflict. Login = phone + password → session/JWT. |
| LK-AUT-05 | Passwords pbkdf2:sha256 (Werkzeug). Change requires current password; new ≥ 6 chars, must differ, optional confirm must match. |
| LK-AUT-06 | Phone change: digits + optional `+`, 8–15 digits, uniqueness. |
| LK-AUT-07 | Guest mode: orders/courier without account (`client_id=None`, `guest_phone`); guest cart via 64-hex `session_token` (read-only server cart). |
| LK-AUT-08 | Profile PUT whitelist: first/last name, email, address, company_name (stripped, empty→None), vehicle_type, license_plate, lat/lon; client-only `preferred_societe_id` (must be active validated societe; empty clears). |
| LK-AUT-09 | Livreur profile GET self-heals `total_deliveries` if below real delivered count. |

### LK-PRC — Pricing & distance
| Rule | Spec |
|---|---|
| LK-PRC-01 | `PRICE_PER_KM = 300` XOF. **No base fee.** |
| LK-PRC-02 | Multipliers (multiplicative): fragile ×1.2, high-value ×1.5 (any line unit price > 50,000 XOF), night ×1.3 (hour < 6 or ≥ 22, UTC — see LK-SEC-03). |
| LK-PRC-03 | Canonical `calculate_delivery_fee` = distance×300 ×fragile ×high_value ×night; fee rounded 0 dp, distance 2 dp. Used by multi-checkout and checkout-preview. |
| LK-PRC-04 | Legacy variants preserved: single-order `/orders`, `/orders/payment`, courier requests → distance×300 ×fragile only. Run price (driver earning) → distance×300 ×fragile ×night (no high-value). See LK-SEC-01. |
| LK-PRC-05 | Haversine R=6371 km; 0 if any coordinate is None. No geocoding (client-sent coords; Lomé defaults 6.16/1.21; supplier fallback 6.13/1.22). |
| LK-PRC-06 | `/estimate-delivery`: public, breakdown {distance_km, base, fragile_bonus?, night_bonus?, high_value_bonus?, total} from request flags. |

### LK-CAT / LK-HRS — Catalog & availability
| Rule | Spec |
|---|---|
| LK-CAT-01 | Public catalog shows only active products of active + admin-validated suppliers. Product detail 404s if inactive. |
| LK-CAT-02 | Filters: supplier_id, category_id, search (ilike product name/description/supplier company). |
| LK-CAT-03 | Supplier list: product_count, average_rating, open_now. Societe list: fleet_count, average_rating. Livreur list: ordered average_rating DESC, total_deliveries DESC; optional min_rating and available_now. |
| LK-HRS-01 | Opening hours per user, day_of_week 0–6 Mon-first; POST **replaces all**; `open == close` → closed that day; overnight windows supported (22:00–06:00); no rows for a day → open. Business TZ Africa/Lome. |

### LK-CRT / LK-CHK — Cart & checkout
| Rule | Spec |
|---|---|
| LK-CRT-01 | Server cart rows (client or guest token + supplier + product). POST accumulates quantity; quantity ≤ 0 removes the row; DELETE one item (`item_id`) or whole cart. POST/DELETE require login; GET allowed by token. |
| LK-CHK-01 | Checkout is **multi-supplier**: one order per supplier. |
| LK-CHK-02 | Preview: per-supplier lines (qty silently capped at stock), product_total, distance_km (supplier→delivery), delivery_fee (LK-PRC-03), subtotal; supplier availability check with French reason; grand totals; amount_due_now / amount_due_on_delivery split. |
| LK-CHK-03 | Multi checkout: creates one order per available supplier, decrements stock at creation, skips unavailable suppliers (`skipped[]` in response). Payment method per checkout: delivery → cash_on_delivery/tmoney/flooz/ecobank; pickup → pay_at_pickup/tmoney/flooz/ecobank. Online methods → simulated tx `success` immediately; cash methods → no tx, payment_status pending. |
| LK-CHK-04 | Legacy single-order endpoints: strict stock (400 aborts whole order if qty > stock), fee = LK-PRC-04, OTP generated, returns {order_id, code, total, otp}. `/orders/payment` adds simulated payment with client flag `simulate_payment_success` (default true) — see LK-SEC-04. |
| LK-CHK-05 | `preferred_societe_id` resolution: checkout param else client profile fallback; must be active validated societe. |

### LK-ORD — Orders
| Rule | Spec |
|---|---|
| LK-ORD-01 | Statuses: CREATED (default), PREPARING, PICKUP_IN_PROGRESS, OUT_FOR_DELIVERY, DELIVERED, CANCELLED, FAILED. Code CMD-+8 hex upper. OTP = 6 hex upper at creation. |
| LK-ORD-02 | List scoping: client→own; fournisseur→own; societe→preferred_societe_id==me; livreur→orders with an assigned run; admin→all. |
| LK-ORD-03 | Detail view permission (`can_view_order`): admin, owning client, owning supplier, preferred societe, livreur with a run. Response includes OTP + qr_token (see LK-SEC-05). |
| LK-ORD-04 | Supplier status endpoint accepts any of the 7 statuses without transition validation; DELIVERED triggers supplier wallet credit. Notifies client. |
| LK-ORD-05 | Pickup actions (`init_pickup` / `confirm_received`): actors = owning client, owning supplier, assigned livreur, admin. Pickup mode without run: init → PICKUP_IN_PROGRESS; confirm → DELIVERED + supplier credit. Delivery mode with run: maps to run transitions PICKUP_INITIATED / PICKED_UP. |

### LK-MSN — Delivery runs (missions)
| Rule | Spec |
|---|---|
| LK-MSN-01 | Statuses: CREATED, ACCEPTED, STARTED, PICKUP_INITIATED, PICKED_UP, IN_TRANSIT, DELIVERED, CANCELLED. |
| LK-MSN-02 | Transition map (enforced): CREATED→{ACCEPTED,STARTED,CANCELLED}; ACCEPTED→{STARTED,CANCELLED}; STARTED→{PICKUP_INITIATED,PICKED_UP,CANCELLED}; PICKUP_INITIATED→{PICKED_UP,CANCELLED}; PICKED_UP→{IN_TRANSIT,DELIVERED,CANCELLED}; IN_TRANSIT→{DELIVERED,CANCELLED}; DELIVERED/CANCELLED terminal. |
| LK-MSN-03 | DELIVERED requires OTP == run.otp_code (case-insensitive) AND, if COD, order payment_status == paid (livreur `confirm_cod_payment`, only from IN_TRANSIT/PICKED_UP, sets paid, no PaymentTransaction row). |
| LK-MSN-04 | Side effects: STARTED/PICKUP_INITIATED→order PICKUP_IN_PROGRESS; PICKED_UP→pickup_time=now, order OUT_FOR_DELIVERY (delivery) or PICKUP_IN_PROGRESS (pickup); IN_TRANSIT→order OUT_FOR_DELIVERY; DELIVERED→delivery_time=now, order DELIVERED, credit livreur + supplier (LK-WAL-01/02). |
| LK-MSN-05 | Every transition notifies the client ("Suivi livraison") + audit `UPDATE_RUN_STATUS`; supplier notified on PICKUP_INITIATED. French labels + next-action hints (`MISSION_STATUS_LABELS`, `MISSION_NEXT_ACTION`) ported verbatim. |
| LK-MSN-06 | Run OTP (6 hex) + qr_token (`token_urlsafe(32)`) generated at assignment. |
| LK-MSN-07 | Public `/validate-delivery` accepts otp OR qr_token → run+order DELIVERED with COD guard, credits wallets (ported as-is, flagged LK-SEC-05). |
| LK-MSN-08 | Run CANCELLED does **not** cancel the order; order cancel does not cancel the run (LK-SEC-06). |

### LK-ASN / LK-CLM — Assignment & claim
| Rule | Spec |
|---|---|
| LK-ASN-01 | Three pools, priority order: ① shop drivers (`likdelivery.shop.driver` active links) — if any exist, only they may be assigned/claim; ② société fleet — if order has preferred_societe_id, only that société/fleet; fournisseur blocked from assigning; ③ platform open claim — `open_for_platform_claim` (set by supplier init-handover with no shop drivers) or status PICKUP_IN_PROGRESS with zero shop drivers and no preferred societe. |
| LK-ASN-02 | Admin may assign any active livreur at any time. |
| LK-ASN-03 | Assignment creates/reuses the single non-CANCELLED run (status ACCEPTED, price per LK-PRC-04), sets order OUT_FOR_DELIVERY, open_for_platform_claim=False, notifies livreur (OTP in body) + client. Double assignment → error. If payment ready and order in CREATED/PREPARING/PICKUP_IN_PROGRESS → order PICKUP_IN_PROGRESS + run PICKUP_INITIATED. |
| LK-ASN-04 | `payment_ready` gates assignment/handover = payment_status paid OR method ∈ {cash_on_delivery, pay_at_pickup}. |
| LK-ASN-05 | `init-handover` (fournisseur/admin): without shop drivers and no assignment → open_for_platform_claim=True; with shop drivers and no assignment → 400 require_shop_assign. |
| LK-CLM-01 | Claim guards (in order): preferred societe → must be fleet member; shop drivers exist & not open → must be shop driver; platform pool requires open_for_platform_claim OR PICKUP_IN_PROGRESS. Success → LK-ASN-03 + order PICKUP_IN_PROGRESS + run PICKUP_INITIATED. Response: delivery_run_id, otp, claim_source ∈ societe/boutique/plateforme. |
| LK-CLM-02 | `available-orders` lists claimable orders with claimable=true + claim_source. |

### LK-WAL — Wallets
| Rule | Spec |
|---|---|
| LK-WAL-01 | Livreur credit on run DELIVERED: total_deliveries += 1; earned += run.price. |
| LK-WAL-02 | Fournisseur credit on order DELIVERED (once, `supplier_wallet_credited` flag): earned += product_total (delivery fees excluded). If product_total ≤ 0, flag set without credit. |
| LK-WAL-03 | Snapshot (authoritative, recomputed on every read): livreur earned = Σ run.price (DELIVERED); fournisseur earned = Σ order.product_total (DELIVERED); withdrawn = Σ withdrawals (completed+pending); available = max(0, round(earned − withdrawn, 0)). |
| LK-WAL-04 | Withdrawal: amount > 0, ≤ available; created instantly with status=completed (no payout workflow); rounded 0 dp; kinds product_sales / delivery_fees; history = last 50. Audit `WALLET_WITHDRAW`. |

### LK-CAN — Cancellation
| Rule | Spec |
|---|---|
| LK-CAN-01 | Blocked statuses: DELIVERED, CANCELLED, FAILED. Client-ownership checked only when caller role == client (gap flagged LK-SEC-02 — ported as-is). |
| LK-CAN-02 | Penalty = first active CancellationRule's penalty_percent (default 80.0). penalty = round(total × pct/100, 0); refund = total − penalty. Time windows and applies_to_* flags are **not evaluated** (dead fields, ported). |
| LK-CAN-03 | Paid order → refund PaymentTransaction (provider="refund", status=success, provider_ref REF-+12, amount=refund). |
| LK-CAN-04 | Unpaid order → no transaction; penalty mentioned in notification text only (no debt record). No restock (LK-SEC-06). Client notified. Audit `CANCEL_ORDER`. |

### LK-PAY — Payments
| Rule | Spec |
|---|---|
| LK-PAY-01 | Providers: tmoney, flooz, ecobank; pseudo: cash_on_delivery, pay_at_pickup, refund, cash. All simulated in v1. |
| LK-PAY-02 | References: PAY-+10 hex; provider_ref PROV-+12; refund REF-+12. Statuses: pending/success/failed/refunded (refunded unused). |
| LK-PAY-03 | `payments/initiate` (public): target order|courier, amount = total|price → tx pending. `payments/<ref>/confirm` (public webhook sim): simulate_success (default true) → success + provider_ref + target paid; else failed + failure_reason. `simulate-payment` legacy alias. |
| LK-PAY-04 | COD: no PaymentTransaction; livreur confirms cash (LK-MSN-03). |

### LK-RAT / LK-REC — Rating & recommendation
| Rule | Spec |
|---|---|
| LK-RAT-01 | Client only; own order; status DELIVERED; stars 1–5; sets order.rating/comment AND latest DELIVERED run of the order. |
| LK-RAT-02 | Livreur average_rating = mean of ALL rated runs, round 2, recomputed per rating. New livreur starts at 5.0. Supplier average_rating never updated (display-only, LK-SEC-07). |
| LK-REC-01 | `recommended-livreurs`: active livreurs; night (param or current) → rating ≥ 4.0; high_value param → ≥ 4.5; order rating DESC, total_deliveries DESC; limit 10. |

### LK-SOC — Société & fleet
| Rule | Spec |
|---|---|
| LK-SOC-01 | Fleet = `likdelivery.fleet.driver` links, origin internal (company resource) | external (independent pro attached). List: internals first. |
| LK-SOC-02 | Create internal: phone, password ≥ 6, names, vehicle_type, license_plate **required** → creates livreur user (validated_by_admin=True, employer_societe_id=societe, rating 5.0) + link origin=internal. Audit `CREATE_INTERNAL_LIVREUR`. |
| LK-SOC-03 | Link external refused if livreur is internal resource of another societe. |
| LK-SOC-04 | DELETE: soft-deactivates link; if livreur is internal resource of this societe → livreur is_active=False. |
| LK-SOC-05 | Edit: names only for internals; vehicle/plate for any linked; internal plate cannot be emptied. |
| LK-SOC-06 | Societe orders: preferred_societe_id==me AND mode=delivery; filter status=open (not CANCELLED/DELIVERED/FAILED) or exact status. |
| LK-SOC-07 | Shop drivers (`likdelivery.shop.driver`): link/unlink (soft), POST reactivates existing link. |

### LK-KYC — KYC
| Rule | Spec |
|---|---|
| LK-KYC-01 | Upload: id_document required (pdf/png/jpg/jpeg), cfe_document optional; filenames kyc_id_<uid>_<8hex>.<ext>. Re-upload **resets validated_by_admin=False**. Notifies user. |
| LK-KYC-02 | Admin: pending-users list (fournisseur/societe not validated), view KYC (audit `VIEW_KYC`), validate → validated_by_admin=True + notify (audit `VALIDATE_USER`). |

### LK-NOT — Notifications
| Rule | Spec |
|---|---|
| LK-NOT-01 | In-app rows; channel field supports in-app/sms/whatsapp (only in-app used; sms/whatsapp simulated). Guests keyed by guest_phone. List = last 50 (own user_id or guest_phone == own phone). Mark-read ownership-checked. |
| LK-NOT-02 | Trigger events: order created (client+supplier), per-supplier multi-order (+ preferred societe), status changes, init-handover, assignment, every run transition, COD confirm, delivery validated, pickup steps, cancellation, KYC submitted, account validated. |
| LK-NOT-03 | Admin send-test: arbitrary {user_id|guest_phone, channel, title, body}. |

### LK-AUD — Audit
| Rule | Spec |
|---|---|
| LK-AUD-01 | Record: actor_id, actor_role, action, target_type, target_id, ip, details JSON. Admin list = last 200. |
| LK-AUD-02 | Action catalogue (36): REGISTER, LOGIN, UPDATE_PROFILE, WALLET_WITHDRAW, CREATE_PRODUCT, UPDATE_PRODUCT, DELETE_PRODUCT, UPLOAD_PRODUCT_IMAGE, UPDATE_OPENING_HOURS, UPLOAD_KYC, VIEW_KYC, CREATE_ORDER, CREATE_ORDER_WITH_PAYMENT, CREATE_MULTI_ORDERS, UPDATE_ORDER_STATUS, SUPPLIER_INIT_HANDOVER, ASSIGN_LIVREUR, LINK_SHOP_LIVREUR, UNLINK_SHOP_LIVREUR, CREATE_INTERNAL_LIVREUR, LINK_SOCIETE_LIVREUR, UNLINK_SOCIETE_LIVREUR, UPDATE_FLEET_LIVREUR, UPDATE_RUN_STATUS, CONFIRM_COD_PAYMENT, INIT_PICKUP, CONFIRM_PICKUP_RECEIVED, VALIDATE_DELIVERY, CREATE_COURIER_REQUEST, CANCEL_ORDER, PAYMENT_INITIATE, PAYMENT_CONFIRM, RATE, VALIDATE_USER. |

### LK-GEO / LK-UPL / LK-ADM
| Rule | Spec |
|---|---|
| LK-GEO-01 | Livreur location push: append-only {lat, lon, accuracy}. Read latest per livreur — **public** in reference (LK-SEC-08). |
| LK-UPL-01 | Uploads: max 5 MB; image ext {png,jpg,jpeg,gif,webp}; KYC adds pdf; random hex filenames (product_<id>_<16hex>, kyc_*_<8hex>); served with Cache-Control max-age=3600. |
| LK-ADM-01 | Stats: counts users/orders/runs/courier_requests/pending_validation, today_orders, total_revenue = Σ all order totals (bugs ported: datetime≥date compare; cancelled included — LK-SEC-09). Analytics: orders/day 14 d, status counts, top 5 suppliers by revenue. Admin orders: last 200 + assignment info. |

### LK-SEC — Known risks & quirks (ported as-is in v1; NOT fixed without business decision)
| ID | Item |
|---|---|
| LK-SEC-01 | Three divergent fee formulas (LK-PRC-03 vs LK-PRC-04): driver payout ≠ collected fee in high-value/night-shift cases. |
| LK-SEC-02 | Cancel authorization gap: client-ownership checked only for role==client. |
| LK-SEC-03 | Night check uses UTC; opening hours use Africa/Lome (coincidentally equal in Lomé). |
| LK-SEC-04 | Payment success is client-controlled (`simulate_payment_success`, default true). Simulator-only; real PSP removes this. |
| LK-SEC-05 | Public `/validate-delivery` (OTP/QR only); OTP/qr_token exposed to all order viewers. |
| LK-SEC-06 | No restock on cancel; run/order states can diverge; unpaid-cancel penalty is text-only debt. |
| LK-SEC-07 | Supplier average_rating never updated. |
| LK-SEC-08 | Public driver GPS read. |
| LK-SEC-09 | Admin stats: datetime≥date comparison; revenue includes cancelled/failed orders. |
| LK-SEC-10 | CourierRequest is a stub: creation + pricing only, no lifecycle endpoints. |
| LK-SEC-11 | Role-check oddities: societe accepted on some supplier endpoints but ownership compared to supplier_id (inert). |
| LK-SEC-12 | Default SECRET_KEY "dev-secret-change-me" must NOT be ported; Odoo secrets via config/env. |
| LK-SEC-13 | Post-assignment "ready bump" in claim/assign-livreur endpoints is **unreachable dead code**: `_assign_livreur_to_order` already sets the order to OUT_FOR_DELIVERY, so the `status in (CREATED, PREPARING, PICKUP_IN_PROGRESS)` condition is never true — the run stays ACCEPTED until the driver acts. Ported as-is. |

---

## §E — Endpoint mapping (64 routes)

> **Amendment (S2, validated)**: auth endpoints are **shared and role-agnostic**
> (rows marked ⚠️) — `POST /api/v1/auth/{register,login,refresh,logout}` +
> `GET /api/v1/auth/me` — mirroring the reference's single `/api/login` for all
> roles, instead of duplicating them per namespace. Auth transport: JWT HS256
> (Bearer, access 1 h / refresh 30 d rotating with jti revocation) **or**
> HttpOnly cookies (`lik_token` / `lik_refresh`) for the PWA. Response envelope:
> `{"ok": true, "data": …}` / `{"ok": false, "code": "STABLE_CODE", "error": …}`.

Legend — Auth: 🌐 public · 👤 login · role names. Service column = `likdelivery_core` service.

### Client API → `/api/v1/client/*`

| # | Flask | Odoo | Auth | Service | Rules |
|---|---|---|---|---|---|
| E01 | POST `/api/register` | POST `/api/v1/auth/register` ⚠️ | 🌐 | core user | LK-AUT-01..04 |
| E02 | POST `/api/login` | POST `/api/v1/auth/login` ⚠️ | 🌐 | api_base auth | LK-AUT-04/05 |
| E03 | POST `/api/logout` | POST `/api/v1/auth/logout` ⚠️ | 👤 | api_base auth | — |
| E04 | GET `/api/me` | GET `/api/v1/auth/me` ⚠️ | 👤 | api_base | — |
| E05 | GET/PUT `/api/profile` | GET/PUT `/api/v1/auth/profile` ⚠️ | 👤 | profile | LK-AUT-05/06/08/09 |
| E06 | GET `/api/categories` | GET `/api/v1/client/catalog/categories` | 🌐 | catalog | LK-CAT-01 |
| E07 | GET `/api/suppliers` | GET `/api/v1/client/catalog/suppliers` | 🌐 | catalog | LK-CAT-03, LK-HRS-01 |
| E08 | GET `/api/products` | GET `/api/v1/client/catalog/products` | 🌐 | catalog | LK-CAT-01/02 |
| E09 | GET `/api/products/<id>` | GET `/api/v1/client/catalog/products/<id>` | 🌐 | catalog | LK-CAT-01 |
| E10 | GET `/api/supplier/opening-hours/<uid>` | GET `/api/v1/client/catalog/suppliers/<uid>/opening-hours` | 🌐 | availability | LK-HRS-01 |
| E11 | GET `/api/societes` | GET `/api/v1/client/catalog/societes` | 🌐 | catalog | LK-CAT-03 |
| E12 | GET `/api/livreurs` | GET `/api/v1/client/catalog/livreurs` | 🌐 | catalog | LK-CAT-03 |
| E13 | GET `/api/recommended-livreurs` | GET `/api/v1/client/catalog/recommended-livreurs` | 🌐 | recommendation | LK-REC-01 |
| E14 | POST `/api/estimate-delivery` | POST `/api/v1/client/estimate-delivery` | 🌐 | pricing | LK-PRC-06 |
| E15 | GET/POST/DELETE `/api/cart` | GET/POST/DELETE `/api/v1/client/cart` | 🌐GET/👤 | cart_service | LK-CRT-01 |
| E16 | POST `/api/cart/checkout-preview` | POST `/api/v1/client/cart/checkout-preview` | 👤 | checkout + pricing | LK-CHK-02, LK-PRC-03 |
| E17 | POST `/api/orders/multi` | POST `/api/v1/client/orders/multi` | 👤 | checkout | LK-CHK-01/03/05 |
| E18 | POST `/api/orders` | POST `/api/v1/client/orders` (legacy) | 🌐 | checkout | LK-CHK-04, LK-PRC-04 |
| E19 | POST `/api/orders/payment` | POST `/api/v1/client/orders/payment` (legacy) | 🌐 | checkout + payment | LK-CHK-04, LK-PAY-01 |
| E20 | GET `/api/orders` | GET `/api/v1/client/orders` | 👤 | order_lifecycle | LK-ORD-02 |
| E21 | GET `/api/orders/<id>` | GET `/api/v1/client/orders/<id>` | 👤 | order_lifecycle | LK-ORD-03 |
| E22 | POST `/api/orders/<id>/cancel` | POST `/api/v1/client/orders/<id>/cancel` | 👤 | cancellation | LK-CAN-01..04 |
| E23 | POST `/api/orders/<id>/pickup-action` | POST `/api/v1/client/orders/<id>/pickup-action` | 👤 | order_lifecycle | LK-ORD-05 |
| E24 | POST `/api/courier-requests` | POST `/api/v1/client/courier-requests` | 🌐 | courier | LK-PRC-04, LK-SEC-10 |
| E25 | POST `/api/rate` | POST `/api/v1/client/rate` | 👤 client | rating | LK-RAT-01/02 |
| E26 | POST `/api/payments/initiate` | POST `/api/v1/client/payments/initiate` | 🌐 | payment_service | LK-PAY-03 |
| E27 | GET `/api/payments/<ref>/status` | GET `/api/v1/client/payments/<ref>/status` | 🌐 | payment_service | LK-PAY-02 |
| E28 | POST `/api/payments/<ref>/confirm` | POST `/api/v1/client/payments/<ref>/confirm` | 🌐 | payment_service | LK-PAY-03, LK-SEC-04 |
| E29 | POST `/api/simulate-payment` | POST `/api/v1/client/payments/simulate` | 🌐 | payment_service | LK-PAY-03 |
| E30 | GET `/api/notifications` | GET `/api/v1/client/notifications` | 👤 | notification | LK-NOT-01 |
| E31 | POST `/api/notifications/<id>/read` | POST `/api/v1/client/notifications/<id>/read` | 👤 | notification | LK-NOT-01 |

### Merchant API → `/api/v1/merchant/*`

| # | Flask | Odoo | Auth | Service | Rules |
|---|---|---|---|---|---|
| E32 | GET/POST `/api/supplier/products` | GET/POST `/api/v1/merchant/products` | fournisseur, admin | catalog | ownership, LK-AUD |
| E33 | PUT/DELETE `/api/supplier/products/<id>` | PUT/DELETE `/api/v1/merchant/products/<id>` | fournisseur, admin | catalog | ownership |
| E34 | POST `/api/supplier/products/<id>/image` | POST `/api/v1/merchant/products/<id>/image` | fournisseur, admin | catalog | LK-UPL-01 |
| E35 | GET/POST `/api/supplier/opening-hours` | GET/POST `/api/v1/merchant/opening-hours` | fournisseur, livreur, societe, admin | availability | LK-HRS-01 |
| E36 | POST `/api/supplier/kyc` | POST `/api/v1/merchant/kyc` | fournisseur, societe, admin | kyc | LK-KYC-01, LK-UPL-01 |
| E37 | GET/POST/DELETE `/api/supplier/livreurs` | GET/POST/DELETE `/api/v1/merchant/shop-drivers` | fournisseur, admin | assignment | LK-SOC-07 |
| E38 | POST `/api/supplier/orders/<id>/status` | POST `/api/v1/merchant/orders/<id>/status` | fournisseur, admin | order_lifecycle | LK-ORD-04 |
| E39 | POST `/api/supplier/orders/<id>/init-handover` | POST `/api/v1/merchant/orders/<id>/init-handover` | fournisseur, admin | assignment | LK-ASN-04/05 |
| E40 | GET `/api/supplier/sales-history` | GET `/api/v1/merchant/sales-history` | fournisseur, admin | wallet | per-day groups, product-only CA |
| E41 | GET `/api/orders` (supplier scope) | GET `/api/v1/merchant/orders` | fournisseur/societe | order_lifecycle | LK-ORD-02, LK-SOC-06 |
| E42 | POST `/api/orders/<id>/assign-livreur` | POST `/api/v1/merchant/orders/<id>/assign-driver` | fournisseur, societe, admin | assignment | LK-ASN-01..04 |
| E43 | GET/POST/DELETE `/api/societe/livreurs` | GET/POST/DELETE `/api/v1/merchant/fleet/drivers` | societe, admin | fleet | LK-SOC-01..04 |
| E44 | PUT `/api/societe/livreurs/<id>` | PUT `/api/v1/merchant/fleet/drivers/<id>` | societe, admin | fleet | LK-SOC-05 |
| E45 | GET `/api/societe/orders` | GET `/api/v1/merchant/fleet/orders` | societe, admin | fleet | LK-SOC-06 |
| E46 | GET `/api/wallet` | GET `/api/v1/merchant/wallet` | fournisseur | wallet | LK-WAL-03/04 |
| E47 | POST `/api/wallet/withdraw` | POST `/api/v1/merchant/wallet/withdraw` | fournisseur | wallet | LK-WAL-04 |

### Driver API → `/api/v1/driver/*`

| # | Flask | Odoo | Auth | Service | Rules |
|---|---|---|---|---|---|
| E48 | GET `/api/livreur/available-orders` | GET `/api/v1/driver/available-orders` | livreur | assignment | LK-CLM-02 |
| E49 | POST `/api/livreur/orders/<id>/claim` | POST `/api/v1/driver/orders/<id>/claim` | livreur | assignment | LK-CLM-01 |
| E50 | GET `/api/livreur/missions` | GET `/api/v1/driver/missions` | livreur | mission_lifecycle | labels + next_action |
| E51 | POST `/api/livreur/missions/<id>/status` | POST `/api/v1/driver/missions/<id>/status` | livreur | mission_lifecycle | LK-MSN-02..05 |
| E52 | POST `/api/livreur/missions/<id>/action` | POST `/api/v1/driver/missions/<id>/action` | livreur | mission_lifecycle | action aliases, LK-MSN-03 |
| E53 | POST `/api/livreur/location` | POST `/api/v1/driver/location` | livreur | geo | LK-GEO-01 |
| E54 | GET `/api/livreur/location/<id>` | GET `/api/v1/driver/location/<id>` | 🌐 (LK-SEC-08) | geo | LK-GEO-01 |
| E55 | POST `/api/validate-delivery` | POST `/api/v1/driver/validate-delivery` | 🌐 (LK-SEC-05) | mission_lifecycle | LK-MSN-07 |
| E56 | GET `/api/wallet` | GET `/api/v1/driver/wallet` | livreur | wallet | LK-WAL-03/04 |
| E57 | POST `/api/wallet/withdraw` | POST `/api/v1/driver/wallet/withdraw` | livreur | wallet | LK-WAL-04 |
| E58 | GET/POST `/api/supplier/opening-hours` | GET/POST `/api/v1/driver/availability` | livreur | availability | LK-HRS-01 |

### Admin → Odoo back-office (no public REST — D7)

| # | Flask | Odoo equivalent |
|---|---|---|
| E59 | GET `/api/admin/pending-users` + POST `/api/admin/users/<id>/validate` | Menu Supervision → Validations KYC + bouton « Valider le compte » (audité) |
| E60 | GET `/api/admin/users/<id>/kyc` | Pièces KYC sur la fiche compte (groupe admin) + bouton « Consulter KYC » audité (`VIEW_KYC`) |
| E61 | GET `/api/admin/orders` | `likdelivery.order` liste + bouton « Assigner un livreur » (wizard → service assignment, source admin) |
| E62 | GET `/api/admin/stats` + `/api/admin/analytics` | Page `/likdelivery/admin/stats` (6 KPIs exacts, quirks LK-SEC-09 portés) + vues graph/pivot |
| E63 | GET `/api/admin/audit-logs` | `likdelivery.audit.log` liste |
| E64 | POST `/api/notifications/send-test` | Wizard « Notification test » (Supervision) |

Static: SPA + `/uploads/*` served by `likdelivery_brand` (E65/E66).

---

## §S — Security matrix (groups × models, summary)

| Model | client | fournisseur | livreur | societe | admin |
|---|---|---|---|---|---|
| `likdelivery.product` | read (active only) | CRUD own | — | — | all |
| `likdelivery.order` | CRU own (create, cancel, rate) | read/update own | read assigned | read preferred | all |
| `likdelivery.delivery.run` | read own orders' runs | read own | R/U assigned | read fleet | all |
| `likdelivery.cart.session` | own / token | — | — | — | all |
| `likdelivery.notification` | own, mark read | own | own | own | all + create |
| `likdelivery.wallet.withdrawal` | — | own + create | own + create | — | read all |
| `likdelivery.driver.location` | — | — | own append | — | read all |
| `likdelivery.fleet.driver` | — | — | — | CRUD own fleet | all |
| `likdelivery.shop.driver` | — | CRUD own | — | — | all |
| `likdelivery.audit.log` | — | — | — | — | read |
| KYC docs (partner fields) | — | own upload | — | own upload | read all |

Anti-BOLA enforced twice: record rules (ORM level) + explicit ownership checks
in services (mirrors Flask `can_view_order` / ownership branches), because some
reference checks are flow-dependent rather than row-static.
