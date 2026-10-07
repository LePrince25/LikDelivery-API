# Livraison Express — Backend (Odoo)

This is the **backend branch** of the Livraison Express platform. It contains only the Odoo 18 monorepo with our custom addons (previously under `delivery/` in the monorepo).

## Stack

- **Odoo 18** Community (Python 3.12)
- **PostgreSQL 16**
- **Custom addons** under `addons/`:
  - `likdelivery_core` — shared models, services, security
  - `likdelivery_api_client` — REST API for shoppers
  - `likdelivery_api_merchant` — REST API for merchants
  - `likdelivery_api_driver` — REST API for drivers
  - `likdelivery_api_societe` — REST API for logistics companies
  - `likdelivery_admin` — admin/manager views

## Local development

```bash
docker compose up -d    # starts Odoo 18 + Postgres 16
```

The Odoo instance is at `http://localhost:8069`. The corresponding Next.js frontend lives on the [`frontend`](https://github.com/afanoupeter2/delivery-/tree/frontend) branch.

## Project layout

```
delivery/
├── addons/
│   ├── likdelivery_core/         # shared models (res.partner, product.template extensions, mission state machine)
│   ├── likdelivery_api_client/   # /api/v1/client/* routes
│   ├── likdelivery_api_merchant/ # /api/v1/merchant/* routes
│   ├── likdelivery_api_driver/   # /api/v1/driver/* routes
│   ├── likdelivery_api_societe/  # /api/v1/societe/* routes
│   └── likdelivery_admin/        # admin/manager views + KYC approval
├── config/
│   └── odoo.conf                # Odoo configuration
├── docs/                        # API contracts, architecture decisions
├── tests/                       # pytest + odoo-test framework
├── docker-compose.yml
└── README.md
```

## API surface

All REST endpoints are versioned under `/api/v1/<role>/`. The contract is documented in `docs/api-contract.md` (or `docs/contracts/` for the per-endpoint specs).

Roles: `client`, `merchant`, `driver`, `societe`, `plateforme` (manager), `admin`.

## Tests

```bash
# Unit + integration tests
docker compose exec odoo pytest -v

# Load Odoo test framework (per-module tests)
docker compose exec odoo odoo-bin -d test_db -i likdelivery_core,likdelivery_api_client --test-enable --stop-after-init
```

## Database

Default Postgres connection (see `config/odoo.conf`):

- host: `db` (docker compose service)
- port: `5432`
- database: `odoo`
- user: `odoo`
- password: `odoo` (development only)

## Current version

`v0.14.0-m13-a11y-chunks` (frontend) — backend changes bundled through M0..M13 (auth, RBAC, catalog, cart, checkout, orders, missions, KYC, fleet, admin).

## License

AGPL-3.0 (Odoo) + Proprietary (custom addons).
