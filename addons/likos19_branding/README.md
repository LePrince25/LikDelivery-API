# likos19_branding

LikOS 19 (Odoo 19) branding module.

Reusable backend theme for LikOS 19 projects: login page, `/likos` web-client routes, and per-company favicon, login logo, and app logo.

## Compatibility

- **LikOS 19** (`liksoft/likos:v19-0-1-*`)
- **Odoo 19** Community

## Install

Copy or clone this repository into an Odoo addons path:

```bash
git clone git@github.com:LikOS-Pro/likos19_branding.git
```

Then install **LikOS 19 Branding** (`likos19_branding`).

Depends only on `web`.

## Branding

Settings → Logos LikOS (one record per company / organization):

- favicon (PNG, ICO, SVG)
- login logo (PNG, JPEG, WebP, SVG)
- app logo (navbar + PWA; PNG, JPEG, WebP, SVG)

The backend uses the current company logos. The login page uses the
organization that matches the request host when LeadBugs portal domains
are installed. Empty fields keep the default LikOS mark. SVG icons are
served as `image/svg+xml` so they display on the login page, favicon,
and navbar. Uploaded logos are served from:

- `/likos/branding/favicon`
- `/likos/branding/login-logo`
- `/likos/branding/app-logo`

The web client address bar stays under `/likos` (Odoo 19's JS router
would otherwise rewrite it to `/odoo/action-…`).

The Settings “About” block shows the application name (`APP_NAME`, default
LikOS) and LIKSOFT copyright instead of Odoo Community / Odoo S.A.

Application name is stored as `ir.config_parameter` key `APP_NAME` (default: `LikOS`).

The installation hook only creates that default when `APP_NAME` is empty. An
existing project name is preserved during installation and upgrades.

## Migration from `likos19_design`

`likos19_branding` supersedes the former `likos19_design` module. Do not keep
both themes enabled in the same database because they override the same login,
navbar, web-client routes, and asset bundles.

For an existing project:

1. back up the database and filestore;
2. record the current `APP_NAME` value;
3. stop normal web traffic and uninstall `likos19_design`;
4. install `likos19_branding` during the same maintenance window;
5. restart Odoo and verify `/web/login`, `/likos`, and `/likos/app-config`;
6. upload project logos from **Settings → Logos LikOS**.

## License

LGPL-3 — [LIKSOFT](https://liksoft.tg)
