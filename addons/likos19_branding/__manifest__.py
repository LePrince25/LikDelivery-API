{
    "name": "LikOS 19 Branding",
    "summary": "Branding module for LikOS 19 (Odoo 19): backend theme, login page, and configurable favicon, login logo, and app logo",
    "version": "19.0.1.3.0",
    "author": "LIKSOFT",
    "website": "https://liksoft.tg",
    "category": "LikOS/Theme",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [
        "security/ir.model.access.csv",
        "data/branding_data.xml",
        "views/branding_views.xml",
        "views/company_views.xml",
        "views/login_templates.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            ("prepend", "likos19_branding/static/src/scss/primary_variables.scss"),
        ],
        "web.assets_backend": [
            "likos19_branding/static/src/scss/backend.scss",
            "likos19_branding/static/src/js/branding.js",
            "likos19_branding/static/src/js/brand_routes.js",
            "likos19_branding/static/src/js/user_menu.js",
            "likos19_branding/static/src/js/edition.js",
            "likos19_branding/static/src/xml/navbar.xml",
            "likos19_branding/static/src/xml/edition.xml",
        ],
        "web.assets_frontend": [
            "likos19_branding/static/src/scss/login.scss",
            "likos19_branding/static/src/js/login_brand.js",
        ],
    },
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "application": False,
    "installable": True,
}
