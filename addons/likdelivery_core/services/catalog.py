"""Catalog service — supplier product CRUD + image upload (E32–E34).

Exact port. Reference: main/app.py lines 827-931.
"""

from .audit import audit_row
from .order_lifecycle import OrderForbidden, OrderNotFound
from .serializers import product_to_dict

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


def list_products(env, lik_user):
    """fournisseur → own; admin → all. Newest first."""
    Product = env["likdelivery.product"].sudo()
    domain = []
    if lik_user.lik_role == "fournisseur":
        domain = [("supplier_id", "=", lik_user.partner_id.id)]
    products = Product.search(domain, order="create_date desc")
    return [product_to_dict(p) for p in products]


def create_product(env, lik_user, data):
    supplier_id = (
        lik_user.partner_id.id
        if lik_user.lik_role == "fournisseur"
        else data.get("supplier_id")
    )
    product = env["likdelivery.product"].sudo().create(
        {
            "supplier_id": supplier_id,
            "category_id": data.get("category_id") or None,
            "name": data.get("name"),
            "description": data.get("description"),
            "price": float(data.get("price", 0)),
            "stock": int(data.get("stock", 0)),
            "fragile": bool(data.get("fragile")),
            "active": bool(data.get("active", True)),
            "lik_image_url": data.get("image_url") or None,
        }
    )
    audit_row(env, lik_user, "CREATE_PRODUCT", "SupplierProduct", product.id)
    return product_to_dict(product)


def _own_product(env, lik_user, product_id):
    product = env["likdelivery.product"].sudo().browse(product_id)
    if not product.exists():
        raise OrderNotFound("Produit inconnu")
    if (
        lik_user.lik_role in ("fournisseur", "societe")
        and product.supplier_id.id != lik_user.partner_id.id
    ):
        raise OrderForbidden("Non autorise")
    return product


def update_product(env, lik_user, product_id, data):
    product = _own_product(env, lik_user, product_id)
    vals = {}
    for field, conv in [
        ("name", str),
        ("description", str),
        ("category_id", int),
        ("price", float),
        ("stock", int),
        ("fragile", bool),
        ("active", bool),
    ]:
        if field in data:
            vals[field] = conv(data[field])
    if "image_url" in data:
        vals["lik_image_url"] = str(data["image_url"])
    if vals:
        product.write(vals)
    audit_row(env, lik_user, "UPDATE_PRODUCT", "SupplierProduct", product.id)
    return product_to_dict(product)


def delete_product(env, lik_user, product_id):
    product = _own_product(env, lik_user, product_id)
    product.unlink()  # hard delete, as the reference
    audit_row(env, lik_user, "DELETE_PRODUCT", "SupplierProduct", product_id)
    return {"message": "Produit supprime"}


def upload_product_image(env, lik_user, product_id, filename, content):
    """LK-UPL-01 — ext whitelist; stored as binary (served via /web/image)."""
    product = _own_product(env, lik_user, product_id)
    if not filename:
        raise ValueError("Nom de fichier vide")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValueError("Format non autorise (png, jpg, jpeg, gif, webp)")
    import base64

    product.image_1920 = base64.b64encode(content)
    audit_row(
        env, lik_user, "UPLOAD_PRODUCT_IMAGE", "SupplierProduct", product.id,
        {"filename": filename},
    )
    return {
        "message": "Image televersee",
        "image_url": f"/web/image/likdelivery.product/{product.id}/image_1920",
        "product_id": product.id,
    }
