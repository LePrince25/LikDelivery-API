"""Canonical serializers — exact ports of the reference *_to_dict shapes.

Home of record (core); likdelivery_api_base.lib.serializers re-exports these
so every namespace emits identical shapes.
"""

from . import availability


def user_to_dict(user):
    """Reference user_to_dict (LK-AUT). `user` is a likdelivery.user."""
    partner = user.partner_id
    return {
        "id": user.id,
        "phone": user.phone,
        "email": user.email or None,
        "role": user.lik_role,
        "first_name": user.lik_first_name or None,
        "last_name": user.lik_last_name or None,
        "address": user.street or None,
        "latitude": user.partner_latitude or None,
        "longitude": user.partner_longitude or None,
        "is_active": user.active,
        "validated_by_admin": user.lik_validated_by_admin,
        "company_name": user.lik_company_name or None,
        "vehicle_type": user.lik_vehicle_type or None,
        "license_plate": user.lik_license_plate or None,
        "average_rating": user.lik_average_rating,
        "total_deliveries": user.lik_total_deliveries or 0,
        "balance": float(partner.lik_wallet_available or 0),
        "preferred_societe_id": user.lik_preferred_societe_id.id or None,
        "employer_societe_id": user.lik_employer_societe_id.id or None,
        "created_at": user.create_date.isoformat() if user.create_date else None,
    }


def category_to_dict(category):
    return {"id": category.id, "name": category.name, "icon": category.icon}


def product_to_dict(product, open_now=None):
    """Reference product_to_dict. open_now precomputed by callers (cache)."""
    supplier = product.supplier_id
    company = (supplier.lik_company_name or "").strip() if supplier else ""
    fallback_name = (
        (
            f"{supplier.lik_first_name or ''} {supplier.lik_last_name or ''}".strip()
            or "Fournisseur"
        )
        if supplier
        else ""
    )
    if open_now is None and product.supplier_id:
        open_now = availability.is_open_now(product.supplier_id)
    if product.image_1920:
        image_url = f"/web/image/likdelivery.product/{product.id}/image_1920"
    else:
        image_url = product.lik_image_url or None
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price": product.price,
        "stock": product.stock,
        "fragile": product.fragile,
        "active": product.active,
        "image_url": image_url,
        "supplier_id": product.supplier_id.id,
        "category_id": product.category_id.id or None,
        "category_name": product.category_id.name or "",
        "supplier_name": company or fallback_name,
        "supplier_company": company,
        "supplier_open_now": bool(open_now) if open_now is not None else True,
        "created_at": product.create_date.isoformat() if product.create_date else None,
        "updated_at": product.write_date.isoformat() if product.write_date else None,
    }


def supplier_to_dict(supplier, product_count, open_now):
    return {
        "id": supplier.id,
        "company_name": supplier.lik_company_name or supplier.lik_first_name or "Fournisseur",
        "phone": supplier.phone,
        "address": supplier.street or None,
        "latitude": supplier.partner_latitude or None,
        "longitude": supplier.partner_longitude or None,
        "product_count": product_count,
        "average_rating": supplier.lik_average_rating,
        "open_now": open_now,
    }


def societe_to_dict(societe, fleet_count):
    return {
        "id": societe.id,
        "company_name": societe.lik_company_name or societe.lik_first_name or "Societe",
        "phone": societe.phone,
        "address": societe.street or None,
        "fleet_count": fleet_count,
        "average_rating": societe.lik_average_rating,
    }
