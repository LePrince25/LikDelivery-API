"""Cart service — server-side multi-supplier cart (LK-CRT-01).

Exact port of the reference /api/cart semantics. Reference: main/app.py
lines 1115-1174.
"""


def supplier_display_name(supplier):
    if not supplier or not supplier.exists():
        return None
    name = f"{supplier.lik_first_name or ''} {supplier.lik_last_name or ''}".strip()
    return supplier.lik_company_name or name or supplier.phone


def _image_url(product):
    if product.image_1920:
        return f"/web/image/likdelivery.product/{product.id}/image_1920"
    return product.lik_image_url or None


def cart_payload(env, lik_user=None, session_token=None):
    """Reference GET shape. Caller decides the identity (user or guest token)."""
    Cart = env["likdelivery.cart.session"].sudo()
    if lik_user:
        rows = Cart.search([("client_id", "=", lik_user.partner_id.id)])
    elif session_token:
        rows = Cart.search([("session_token", "=", session_token)])
    else:
        return []
    result = []
    for item in rows:
        product = item.product_id
        if not product.exists():
            continue
        result.append(
            {
                "id": item.id,
                "supplier_id": item.supplier_id.id,
                "supplier_name": supplier_display_name(item.supplier_id) or "Fournisseur",
                "product_id": product.id,
                "product_name": product.name,
                "quantity": item.quantity,
                "unit_price": product.price,
                "image_url": _image_url(product),
            }
        )
    return result


def add_to_cart(env, lik_user, product_id, quantity):
    """LK-CRT-01 — accumulate; quantity <= 0 removes; create only if > 0.

    Raises ValueError('Produit invalide') for unknown/inactive products.
    """
    product = env["likdelivery.product"].sudo().browse(product_id)
    if not product.exists() or not product.active:
        raise ValueError("Produit invalide")
    Cart = env["likdelivery.cart.session"].sudo()
    existing = Cart.search(
        [("client_id", "=", lik_user.partner_id.id), ("product_id", "=", product_id)],
        limit=1,
    )
    if existing:
        existing.quantity += quantity
        if existing.quantity <= 0:
            existing.unlink()
    elif quantity > 0:
        Cart.create(
            {
                "client_id": lik_user.partner_id.id,
                "supplier_id": product.supplier_id.id,
                "product_id": product_id,
                "quantity": quantity,
            }
        )


def clear_cart(env, lik_user, item_id=None):
    """DELETE one row (item_id) or the whole cart of the user."""
    Cart = env["likdelivery.cart.session"].sudo()
    domain = [("client_id", "=", lik_user.partner_id.id)]
    if item_id:
        domain.append(("id", "=", int(item_id)))
    Cart.search(domain).unlink()


def cart_items(env, lik_user):
    return (
        env["likdelivery.cart.session"]
        .sudo()
        .search([("client_id", "=", lik_user.partner_id.id)])
    )
