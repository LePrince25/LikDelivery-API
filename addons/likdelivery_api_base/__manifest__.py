{
    "name": "Lik Delivery API Base",
    "version": "19.0.1.0.0",
    "category": "Services/Delivery",
    "summary": "Shared REST API plumbing: envelope, JWT auth, rate limiting, idempotency",
    "description": """
Shared plumbing for all /api/v1/* namespaces (client, merchant, driver,
third-party). Contains NO business logic: JSON envelope, error catalogue,
JWT HS256 dual-mode auth (Bearer + HttpOnly cookie), rate limiting,
idempotency keys. Business behavior lives in likdelivery_core services.
""",
    "author": "Liksoft",
    "license": "LGPL-3",
    "depends": ["likdelivery_core"],
    "data": [],
    "installable": True,
    "application": False,
}
