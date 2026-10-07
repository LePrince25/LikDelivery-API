# Regression harness — Flask reference vs Odoo platform

Runs identical business scenarios against both stacks and diffs the normalized
responses, field by field. Stdlib only (`urllib`, `json`, `http.cookiejar`) — no
dependencies to install.

## Prerequisites

Both stacks must be up:

- **Flask reference** on http://localhost:5001
  (`cd main && docker compose -f docker-compose.dev5001.yml up -d --build`)
- **Odoo platform** on http://localhost:9410
  (`cd delivery && docker compose up -d` — already running, do not restart)

Demo accounts must exist on both: fournisseur2 `+22800000005 / afi123`
(Boutique Afi). Everything else (clients, livreurs) is registered on the fly
with unique phones per run, so the suite is re-runnable against dirty databases.

## Run

```bash
python3 run_regression.py            # all scenarios
python3 run_regression.py S04 S06    # selected scenarios
```

Exit code: `0` when every scenario is PASS or KNOWN (documented divergence),
`1` if any scenario FAILs or ERRORs.

## Output

Console prints one line per scenario plus the first diff, e.g.:

```
[S04] cart + checkout preview COD ... PASS (1.8s)
[S09] negative cases ... KNOWN (7.5s)
    first diff: duplicate_register.error: 'Telephone deja utilise' != 'Ce numero de telephone est deja utilise'
```

`report.json` (written next to this file) contains per-scenario `status`,
`first_diff`, full `diffs`, allowlisted `known_diffs`, and `errors`, plus
totals. Diff lines use dotted paths: `groups[0].delivery_fee: 788.0 != 789.0`
means Flask (left) vs Odoo (right).

Statuses: **PASS** (identical), **KNOWN** (only allowlisted divergences),
**FAIL** (real diff), **ERROR** (a stack raised/returned an unexpected error).

## How comparison works

Responses are normalized before diffing: volatile keys are masked recursively
(`id`, `*_id`, `code`, `otp*`, `qr_token`, `reference`, `provider_ref`,
`*_at`, `delivery_time`, `pickup_time`, `server_local_time`, `transaction_id`,
`delivery_run_id`, `link_id`, `livreur_id`, `session_token`, `image_url`).
`null` / `false` / `""` are unified (Odoo emits `false` for unset strings),
numbers are rounded to 2 decimals. Everything else — names, prices, totals,
fees, distances, statuses, counts, booleans, French message strings — must
match exactly.

Entities are matched by semantic keys (product name, company name, order code),
never by id, because each stack has its own id space. The Flask
fournisseur order list is compared against Odoo `/api/v1/merchant/orders`
(role-aware path mapping in `OdooClient`).

## Scenarios

| ID | Covers |
|----|--------|
| S01 | catalog: categories, suppliers, products (deduped by supplier+name), product detail, opening hours |
| S02 | estimate-delivery: 4 flag combinations (none/fragile/night/high_value) |
| S03 | register + login + me + profile, field by field |
| S04 | cart (2 products, one fragile) + checkout preview COD: groups/totals/amount_due_* |
| S05 | multi-supplier checkout COD: per-order totals, payment_status, skipped |
| S06 | full mission: init-handover → claim → start/init_pickup/confirm_received/en_route/confirm_cod_payment/deliver(OTP), status at each step, livreur wallet, supplier sales delta |
| S07 | cancellation of a paid order: penalty/refund/penalty_percent |
| S08 | rating 4 then 2: livreur_average_rating after each |
| S09 | negative cases: wrong login, duplicate register, product 404, invalid transition, BOLA |
| S10 | courier request price (standard + fragile) |
| S11 | livreur wallet withdraw: half of available, message + resulting balance |

## Known divergences (allowlisted in `KNOWN_DIFFS`)

1. **Wrong-login error wording** (both HTTP 401): Flask says
   `Telephone ou mot de passe incorrect`, Odoo says `Identifiants invalides`.
2. **Duplicate-register error wording** (both HTTP 409): Flask says
   `Telephone deja utilise`, Odoo says `Ce numero de telephone est deja utilise`.
3. **Opening-hours data** (S01): the Odoo database has a leftover extra window
   (Monday 08:00–20:00) from earlier manual testing; the 7 seeded windows
   (06:00–23:00 daily) match exactly. Similarly, Odoo's catalog contains
   duplicated migrated products — S01 dedupes by (supplier, product name)
   before comparing, and product `stock` is excluded from the product-detail
   diff because stock drifts with each stack's own order history.

Items 1 and 2 are message-parity bugs worth fixing on the Odoo side if exact
French wording parity is required.
