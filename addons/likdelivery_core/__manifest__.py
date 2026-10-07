{
    "name": "Lik Delivery Core",
    "version": "19.0.1.0.0",
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
        "wizard/lik_wizard_views.xml",
        "views/likdelivery_views.xml",
        "views/likdelivery_menus.xml",
    ],
    "post_init_hook": "_post_init_seed_demo",
    "application": True,
    "installable": True,
}
