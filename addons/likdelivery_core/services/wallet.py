"""Wallet service — credit helpers (LK-WAL-01/02).

The balance itself is a computed field on res.partner (D6, LK-WAL-03) —
these helpers only maintain the counters/flags the reference maintains.
"""


def credit_livreur_delivery(livreur, amount):
    """LK-WAL-01 — on run DELIVERED: total_deliveries += 1.
    (reference also incremented the denormalized balance; ours is computed)."""
    if not livreur or not livreur.exists():
        return
    livreur.sudo().lik_total_deliveries = (livreur.lik_total_deliveries or 0) + 1


def credit_supplier_sale(env, order):
    """LK-WAL-02 — on order DELIVERED, once: supplier earns product_total
    (delivery fees excluded). Guarded by supplier_wallet_credited; orders
    with product_total <= 0 are flagged without credit."""
    if not order or not order.supplier_id:
        return
    if order.supplier_wallet_credited:
        return
    order.sudo().supplier_wallet_credited = True


def snapshot(partner):
    """LK-WAL-03 — authoritative wallet view (reference _wallet_snapshot).

    earned: livreur → Σ run.price (DELIVERED); fournisseur → Σ
    order.product_total (DELIVERED). withdrawn: Σ withdrawals
    (completed+pending). available = max(0, round(earned − withdrawn, 0)).
    """
    env = partner.env
    earned = 0.0
    if partner.lik_role == "livreur":
        runs = env["likdelivery.delivery.run"].sudo().search(
            [("livreur_id", "=", partner.id), ("state", "=", "DELIVERED")]
        )
        earned = sum(runs.mapped("price"))
    elif partner.lik_role == "fournisseur":
        orders = env["likdelivery.order"].sudo().search(
            [("supplier_id", "=", partner.id), ("state", "=", "DELIVERED")]
        )
        earned = sum(orders.mapped("product_total"))
    withdrawn = sum(
        env["likdelivery.wallet.withdrawal"]
        .sudo()
        .search(
            [("user_id", "=", partner.id), ("state", "in", ["completed", "pending"])]
        )
        .mapped("amount")
    )
    available = max(0.0, round(earned - withdrawn, 0))
    kind = "delivery_fees" if partner.lik_role == "livreur" else "product_sales"
    label = "Frais de livraison" if partner.lik_role == "livreur" else "Ventes produits"
    return {
        "role": partner.lik_role,
        "kind": kind,
        "label": label,
        "earned": round(earned, 0),
        "withdrawn": round(withdrawn, 0),
        "available": available,
        "balance": available,
    }


def wallet_payload(env, lik_user):
    """GET wallet: snapshot + last 50 withdrawals."""
    partner = lik_user.partner_id
    snap = snapshot(partner)
    history = (
        env["likdelivery.wallet.withdrawal"]
        .sudo()
        .search([("user_id", "=", partner.id)], order="create_date desc", limit=50)
    )
    return {
        **snap,
        "history": [
            {
                "id": w.id,
                "amount": w.amount,
                "kind": w.kind,
                "status": w.state,
                "note": w.note,
                "created_at": w.create_date.isoformat() if w.create_date else None,
            }
            for w in history
        ],
    }


def withdraw(env, lik_user, amount, note=None):
    """LK-WAL-04 — instant withdrawal (status=completed). Exact messages."""
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        raise ValueError("Montant invalide")
    if amount <= 0:
        raise ValueError("Le montant doit etre superieur a 0")
    partner = lik_user.partner_id
    snap = snapshot(partner)
    if amount > snap["available"]:
        raise WalletInsufficient(
            f"Solde insuffisant. Disponible: {snap['available']:.0f} XOF ({snap['label']})",
            available=snap["available"],
        )
    withdrawal = env["likdelivery.wallet.withdrawal"].sudo().create(
        {
            "user_id": partner.id,
            "role": lik_user.lik_role,
            "amount": round(amount, 0),
            "kind": snap["kind"],
            "state": "completed",
            "note": (note or f"Retrait {snap['label']}").strip()[:255],
        }
    )
    snap2 = snapshot(partner)
    return {
        "message": "Retrait initialise avec succes",
        "withdrawal": {
            "id": withdrawal.id,
            "amount": withdrawal.amount,
            "kind": withdrawal.kind,
            "status": withdrawal.state,
            "note": withdrawal.note,
            "created_at": withdrawal.create_date.isoformat()
            if withdrawal.create_date
            else None,
        },
        "wallet": snap2,
        "_audit": {"amount": amount, "kind": snap["kind"], "id": withdrawal.id},
    }


class WalletInsufficient(ValueError):
    def __init__(self, message, available=0.0):
        super().__init__(message)
        self.available = available
