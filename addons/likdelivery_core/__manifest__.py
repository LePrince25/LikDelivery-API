{
    "name": "Lik Delivery Core",
    "version": "19.0.1.2.0",
    "category": "Services/Delivery",
    "summary": "Livraison Express — business core (models, rules, security, demo data)",
    "description": """
Central business core of the Livraison Express platform.
Ports the validated Flask reference (main/) behavior to Odoo.
All business rules are numbered in delivery/docs/02-traceability-matrix.md.
""",
    "author": "Liksoft",
    "license": "LGPL-3",
    "depends": ["base", "mail", "contacts"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "wizard/lik_wizard_views.xml",
        "views/likdelivery_views.xml",
        "views/res_users_views.xml",
        "views/likdelivery_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "likdelivery_core/static/src/dashboard/dashboard.scss",
            "likdelivery_core/static/src/dashboard/charts.js",
            "likdelivery_core/static/src/dashboard/dashboard.js",
            "likdelivery_core/static/src/dashboard/charts.xml",
            "likdelivery_core/static/src/dashboard/dashboard.xml",
        ],
    },
    "post_init_hook": "_post_init_seed_demo",
    "application": True,
    "installable": True,
}
