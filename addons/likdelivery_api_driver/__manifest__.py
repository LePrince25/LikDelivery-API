{
    "name": "Lik Delivery API Driver",
    "version": "19.0.1.0.0",
    "category": "Services/Delivery",
    "summary": "Driver REST API (/api/v1/driver/*) — livreur namespace",
    "description": """
Driver namespace: available orders, claim, missions (status/action),
COD confirmation, OTP/QR delivery validation, GPS location, wallet,
availability hours. Thin controllers over likdelivery_core services.
""",
    "author": "Liksoft",
    "license": "LGPL-3",
    "depends": ["likdelivery_api_base"],
    "data": [],
    "installable": True,
    "application": False,
}
