{
    "name": "Lik Delivery Brand",
    "version": "19.0.1.0.0",
    "category": "Services/Delivery",
    "summary": "Livraison Express — branding freeze, PWA hosting and primary color",
    "description": """
Brands the platform as Livraison Express (APP_NAME, likos.branding logos),
serves the reference PWA at / and overrides the backend primary color.
""",
    "author": "Liksoft",
    "license": "LGPL-3",
    "depends": ["likdelivery_core", "likos19_branding"],
    "data": [
        "data/brand_data.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            ("prepend", "likdelivery_brand/static/src/scss/primary_variables.scss"),
        ],
    },
    "post_init_hook": "_post_init_brand",
    "application": False,
    "installable": True,
}
