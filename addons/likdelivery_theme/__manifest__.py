{
    "name": "LikDelivery Theme",
    "version": "19.0.1.1.0",
    "category": "Extra Tools",
    "summary": "Design system LikDelivery (clair/bleu) applique au backend et aux pages d'authentification",
    "description": """
Reprend les tokens --pl-* de LikDelivery-Web (src/app/globals.css, theme
clair) et les mappe sur la palette du client web Odoo : surfaces blanches,
accents bleu royal, radius, typographies, logo, favicon, page de login.
""",
    "author": "Liksoft",
    "website": "https://likdelivery.com",
    "license": "LGPL-3",
    "depends": ["web", "likdelivery_core"],
    "data": [
        "views/theme_templates.xml",
        "views/login_templates.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            "likdelivery_theme/static/src/scss/primary_variables.scss",
        ],
        "web.assets_backend": [
            "likdelivery_theme/static/src/scss/backend.scss",
            "likdelivery_theme/static/src/xml/navbar.xml",
        ],
        "web.assets_frontend": [
            "likdelivery_theme/static/src/scss/auth.scss",
        ],
    },
    "application": False,
    "installable": True,
}
