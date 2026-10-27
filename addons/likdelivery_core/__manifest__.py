{
    "name": "Lik Delivery Core",
    "version": "19.0.1.1.0",
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
    "post_init_hook": "_post_init_seed_demo",
    "assets": {
        "web.assets_backend": [
            "likdelivery_core/static/src/views/dashboard/dashboard_view.js",
            "likdelivery_core/static/src/views/dashboard/dashboard_view.xml",
            "likdelivery_core/static/src/views/dashboard/dashboard_view.scss",
        ],
    },
    "application": True,
    "installable": True,
}
