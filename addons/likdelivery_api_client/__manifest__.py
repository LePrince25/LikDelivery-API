{
    "name": "Lik Delivery API Client",
    "version": "19.0.1.0.0",
    "category": "Services/Delivery",
    "summary": "Client REST API (/api/v1/client/*) — thin controllers over likdelivery_core",
    "description": """
Client namespace: public catalog, cart, checkout, orders, courier requests,
payments, rating, notifications. No business logic here — controllers
delegate to likdelivery_core services.
""",
    "author": "Liksoft",
    "license": "LGPL-3",
    "depends": ["likdelivery_api_base"],
    "data": [],
    "installable": True,
    "application": False,
}
