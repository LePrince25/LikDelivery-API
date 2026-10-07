"""Re-export of the canonical serializers (home: likdelivery_core.services).
Kept for backward compatibility of existing imports."""

from odoo.addons.likdelivery_core.services.serializers import (  # noqa: F401
    category_to_dict,
    product_to_dict,
    societe_to_dict,
    supplier_to_dict,
    user_to_dict,
)
