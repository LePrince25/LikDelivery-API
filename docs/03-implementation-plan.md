# 03 — Implementation Plan

Scope: build the Odoo platform per `01-architecture-cible.md`, porting every
rule of `02-traceability-matrix.md`. No behavior changes. 12 one-week sprints.

---

## 1. Sprint plan

| Sprint | Deliverable | Rules covered | Acceptance gate |
|---|---|---|---|
| S1 | Docker stack (Odoo 19 + PG16), `likdelivery_core` skeleton, all 17 models + fields, groups, demo data (seed.py port) | M1–M17, LK-AUT-01..04 | Demo install one command; models visible in back-office |
| S2 | `likdelivery_api_base`: envelope, error catalogue, JWT + session dual auth, idempotency, rate limit | LK-AUT-04/05, LK-SEC-12 | Login/me/logout via JWT + cookie; pbkdf2 hashes verified |
| S3 | Services: `pricing`, `availability`, `recommendation`; client catalog endpoints E06–E14 | LK-PRC, LK-CAT, LK-HRS, LK-REC | Pricing unit matrix green (§5.1) |
| S4 | Services: `cart_service`, `checkout` (preview); endpoints E15–E16 | LK-CRT, LK-CHK-02 | Preview totals match Flask on golden scenarios |
| S5 | Checkout creation: multi-order, legacy orders, payment-at-checkout; endpoints E17–E19, E24 | LK-CHK-01/03/04/05, LK-PAY-01 | Orders created per supplier; stock decremented; skipped[] correct |
| S6 | Order lifecycle: list/detail scoping, pickup actions, supplier status; endpoints E20–E23, E38, E41 | LK-ORD | BOLA tests green (§5.3) |
| S7 | Mission lifecycle: state machine, OTP/COD, validate-delivery; endpoints E50–E52, E55 | LK-MSN | Transition matrix exhaustive test green |
| S8 | Assignment & claim: 3 pools, init-handover, assign-driver, available-orders; endpoints E37, E39, E42, E48–E49 | LK-ASN, LK-CLM | Pool priority scenarios green |
| S9 | Wallets + cancellation + rating; endpoints E22, E25, E40, E46–E47, E56–E57 | LK-WAL, LK-CAN, LK-RAT | Wallet arithmetic vs Flask; 80/20 cases |
| S10 | Société fleet + shop drivers + KYC; endpoints E35–E36, E43–E45, E58; geo E53–E54 | LK-SOC, LK-KYC, LK-GEO, LK-UPL | Fleet internal/external flows green |
| S11 | Payments simulator full surface (E26–E29), notifications (E30–E31), admin back-office views (E59–E64), audit | LK-PAY, LK-NOT, LK-AUD, LK-ADM | Audit catalogue 36 actions verified |
| S12 | `likdelivery_brand` + PWA rewire, `likdelivery_migration` ETL + reconciliation, regression suite full run, cutover runbook | all | §4 report 100% + §5 suite green on both stacks |

`likdelivery_api_thirdparty` (API keys / OAuth2) lands after S12 as v1.1
(its plumbing — JWT, envelope, services — is already in place; only the
credential model, scopes, and token endpoint are new).

## 2. Module build order & dependencies

```
likdelivery_core            (S1–S11, incremental)
  └─ likdelivery_api_base   (S2)
       ├─ likdelivery_api_client    (S3–S6, S9, S11)
       ├─ likdelivery_api_merchant  (S6, S8–S10)
       ├─ likdelivery_api_driver    (S7–S10)
       └─ likdelivery_api_thirdparty (v1.1)
likdelivery_migration       (S12, depends core)
likdelivery_brand           (S12, depends api_client)
```

Per-module layout (standard Odoo): `__manifest__.py`, `models/`, `services/`
(core only), `controllers/` (api modules), `security/`, `views/`, `demo/`,
`tests/`.

## 3. Data migration (safe, no loss)

Strategy: **blue/green, ID-preserving ETL, reconciliation-gated cutover.**

1. **Preflight**: backup `instance/livraison.db`; run reference `init_db()`
   to apply soft column migrations; freeze writes (Flask read-only).
2. **Extract**: read SQLite directly (SQLAlchemy models of the reference —
   same class definitions, no re-modeling).
3. **Transform**: map rows per §M of the matrix. Key points:
   - `users` → split into `res.partner` + `likdelivery.user` (+ `res.users`
     only for role=admin). Password hashes copied verbatim (pbkdf2 compatible).
   - Polymorphic `payment_transactions.target_*` → concrete m2o pairs.
   - `balance` column is **not migrated** — it is a cache; Odoo computes it
     (D6). Reconciliation recomputes both sides from history.
4. **Load**: Odoo ORM import with **explicit `id`** preservation so codes,
   FK graphs, and audit trails stay coherent; sequences reset above max id.
5. **Validate** (blocking gate): per-entity reconciliation report —
   - row counts per table;
   - Σ order.total, Σ run.price, Σ withdrawal.amount per user;
   - recomputed wallet available per user, Flask vs Odoo (must be equal);
   - spot-check: serialize N random orders on both stacks → JSON diff empty;
   - all order codes / payment references unique and present.
6. **Cutover**: regression suite green → DNS switch app → Odoo; Flask kept
   read-only for 1 month as rollback (rollback = DNS flip back).

## 4. Regression test strategy (Flask ≡ Odoo)

### 5.1 Unit-port tests (Odoo `TransactionCase`)
- **Pricing matrix**: distance × {day/night} × {fragile} × {high-value} ×
  all three formula variants (LK-PRC-03/04) — exact rounding asserted.
- **Mission transitions**: every legal transition succeeds with correct side
  effects; every illegal pair rejected (`MISSION_TRANSITION_INVALID`);
  DELIVERED blocked without OTP / with COD unpaid.
- **Wallet**: earned/withdrawn/available arithmetic incl. floor 0, rounding,
  double-credit guard (`supplier_wallet_credited`).
- **Cancellation**: paid → 20% refund tx; unpaid → no tx; blocked statuses.
- **Recommendation**: 4.0/4.5 thresholds, ordering, limit 10.
- **Availability**: overnight windows, closed-day, no-rows-open.

### 5.2 Golden-master API tests (cross-stack)
Scenario suite (extended Postman collection) executed against **both** Flask
(:5001) and Odoo; responses normalized (ids, timestamps, references masked)
and diffed. Scenarios: full client journey (register→catalog→cart→preview→
multi-checkout→pay→track→rate→cancel), supplier journey (CRUD→hours→KYC→
process→handover→sales→withdraw), driver journey (claim→transitions→COD→
OTP→wallet), société fleet, guest orders, edge cases (stock cap, closed
shop, double assignment, illegal transitions).

### 5.3 Security tests (port of `tests/test_security.py`, fixed)
The 7 existing cases (BOLA order read, admin RBAC, password hashing, product
ownership, rating ownership, multi-supplier cart, 80% penalty) — re-based off
the hard-coded paths/seed assumptions of the current file — plus record-rule
level BOLA tests per model (§S matrix).

### 5.4 Migration validation
The §3.5 reconciliation report must be 100% green before cutover; report
artifact archived per run.

## 5. Cutover runbook (S12 output)

1. Deploy Odoo (prod compose, Nginx, TLS).
2. Load demo data → smoke test.
3. Freeze Flask → ETL → reconciliation green.
4. Point PWA at `/api/v1/*` (single `API` base change in `app.js` + JWT).
5. Regression suite against production candidate.
6. DNS cutover; monitor 24 h; Flask read-only standby 1 month.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Divergent fee formulas discovered late | S3 pricing matrix test against Flask outputs first |
| BOLA regressions in thin controllers | Double enforcement (record rules + service checks), §S tests in S6 |
| Wallet divergence (cache vs computed) | Never store balance; reconciliation recomputes from history |
| OTP/QR secrets in API responses | Ported as reference (LK-SEC-05); third-party module gets redacted serializers |
| Odoo upgrade (19 → later) | All logic in custom modules; no core overrides; services framework-free |
