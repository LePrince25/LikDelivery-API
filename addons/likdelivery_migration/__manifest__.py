{
    "name": "Lik Delivery Migration",
    "version": "19.0.1.0.0",
    "category": "Services/Delivery",
    "summary": "One-shot ETL: import the Flask/SQLite reference data into likdelivery_core",
    "description": """
One-shot migration tool (NOT an API) that imports the legacy Flask
reference database (SQLite, main/instance/livraison.db) into the
likdelivery_core models. No ID preservation (likdelivery.migration.map),
idempotent, pbkdf2 hashes copied verbatim, reconciliation report.
Usage: see README.md.
""",
    "author": "Liksoft",
    "license": "LGPL-3",
    "depends": ["likdelivery_core"],
    "data": [
        "security/ir.model.access.csv",
        "views/migration_views.xml",
    ],
    "installable": True,
    "application": False,
}
