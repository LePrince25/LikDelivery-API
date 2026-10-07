"""Fleet service — shop drivers (E37) + société fleet (E43–E45) +
société orders (E45). Exact port (LK-SOC-01..07).

Reference: main/app.py lines 2003-2057 (shop), 2089-2291 (fleet + orders).
"""

from .audit import audit_row
from .order_lifecycle import OrderNotFound, order_to_dict
from .serializers import user_to_dict


def _societe_id_for(env, lik_user, data=None, args=None):
    if lik_user.lik_role == "societe":
        return lik_user.partner_id.id
    raw = (data or {}).get("societe_id") or (args or {}).get("societe_id")
    if not raw:
        raise ValueError("societe_id requis pour admin")
    return int(raw)


def _livreur_dict(lik_user_record, link=None, origin=None):
    d = user_to_dict(lik_user_record)
    if link is not None:
        d["link_id"] = link.id
    if origin is not None:
        d["origin"] = origin
        d["is_internal"] = origin == "internal"
        d["resource_label"] = (
            "Ressource societe" if origin == "internal" else "Livreur externe (pro)"
        )
    return d


def _lik_user_for_partner(env, partner_id):
    return env["likdelivery.user"].sudo().search(
        [("partner_id", "=", partner_id)], limit=1
    )


# ---------------- Shop drivers (E37) ----------------

def shop_drivers_list(env, lik_user, supplier_id=None):
    sid = lik_user.partner_id.id
    if lik_user.lik_role == "admin" and supplier_id:
        sid = int(supplier_id)
    links = env["likdelivery.shop.driver"].sudo().search(
        [("supplier_id", "=", sid), ("is_active", "=", True)]
    )
    result = []
    for link in links:
        liv = link.livreur_id
        if liv and liv.lik_role == "livreur" and liv.active:
            result.append(_livreur_dict(_lik_user_for_partner(env, liv.id), link=link))
    return result


def shop_driver_link(env, lik_user, livreur_id, supplier_id=None):
    sid = lik_user.partner_id.id
    if lik_user.lik_role == "admin" and supplier_id:
        sid = int(supplier_id)
    livreur = env["res.partner"].sudo().search(
        [("id", "=", livreur_id), ("lik_role", "=", "livreur"), ("active", "=", True)],
        limit=1,
    )
    if not livreur:
        raise ValueError("Livreur invalide")
    Link = env["likdelivery.shop.driver"].sudo()
    existing = Link.search(
        [("supplier_id", "=", sid), ("livreur_id", "=", livreur_id)], limit=1
    )
    if existing:
        existing.is_active = True
    else:
        Link.create({"supplier_id": sid, "livreur_id": livreur_id, "is_active": True})
    audit_row(env, lik_user, "LINK_SHOP_LIVREUR", "User", livreur_id, {"supplier_id": sid})
    return {"message": "Livreur associe a la boutique"}


def shop_driver_unlink(env, lik_user, livreur_id, supplier_id=None):
    sid = lik_user.partner_id.id
    if lik_user.lik_role == "admin" and supplier_id:
        sid = int(supplier_id)
    link = env["likdelivery.shop.driver"].sudo().search(
        [("supplier_id", "=", sid), ("livreur_id", "=", int(livreur_id))], limit=1
    )
    if not link:
        raise OrderNotFound("Association introuvable")
    link.is_active = False
    audit_row(
        env, lik_user, "UNLINK_SHOP_LIVREUR", "User", int(livreur_id),
        {"supplier_id": sid},
    )
    return {"message": "Livreur retire de la boutique"}


# ---------------- Société fleet (E43–E45) ----------------

def fleet_list(env, lik_user, data=None, args=None):
    sid = _societe_id_for(env, lik_user, data, args)
    links = env["likdelivery.fleet.driver"].sudo().search(
        [("societe_id", "=", sid), ("is_active", "=", True)]
    )
    result = []
    for link in links:
        liv = link.livreur_id
        if liv and liv.lik_role == "livreur" and liv.active:
            origin = link.origin or (
                "internal" if liv.lik_employer_societe_id.id == sid else "external"
            )
            result.append(
                _livreur_dict(_lik_user_for_partner(env, liv.id), link=link, origin=origin)
            )
    # internals first
    result.sort(
        key=lambda x: (0 if x.get("is_internal") else 1, (x.get("first_name") or x.get("phone") or ""))
    )
    return result


def fleet_create_internal(env, lik_user, data):
    """LK-SOC-02 — create a company-owned driver account + internal link."""
    sid = _societe_id_for(env, lik_user, data)
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    vehicle_type = (data.get("vehicle_type") or "").strip() or None
    license_plate = (data.get("license_plate") or "").strip() or None
    if not phone or not password:
        raise ValueError("Telephone et mot de passe requis")
    if len(password) < 6:
        raise ValueError("Mot de passe: au moins 6 caracteres")
    if not license_plate:
        raise ValueError("Plaque d'immatriculation requise pour un livreur interne")
    User = env["likdelivery.user"].sudo()
    if User.search_count([("phone", "=", phone)]):
        raise FileExistsError("Ce telephone est deja utilise")
    liv = User.create(
        {
            "name": f"{first_name} {last_name}".strip() or phone,
            "phone": phone,
            "lik_role": "livreur",
            "lik_first_name": first_name or None,
            "lik_last_name": last_name or None,
            "lik_vehicle_type": vehicle_type,
            "lik_license_plate": license_plate,
            "lik_validated_by_admin": True,
            "active": True,
            "lik_employer_societe_id": sid,
            "lik_average_rating": 5.0,
        }
    )
    liv.set_password(password)
    env["likdelivery.fleet.driver"].sudo().create(
        {
            "societe_id": sid,
            "livreur_id": liv.partner_id.id,
            "is_active": True,
            "origin": "internal",
        }
    )
    audit_row(
        env, lik_user, "CREATE_INTERNAL_LIVREUR", "User", liv.id,
        {"societe_id": sid, "plate": license_plate},
    )
    out = user_to_dict(liv)
    out["origin"] = "internal"
    out["is_internal"] = True
    return {
        "message": "Livreur interne cree et ajoute a la flotte",
        "livreur": out,
        "_status": 201,
    }


def fleet_link_external(env, lik_user, data):
    """LK-SOC-03 — attach an independent pro (refused if internal elsewhere)."""
    sid = _societe_id_for(env, lik_user, data)
    livreur_id = data.get("livreur_id")
    livreur = env["res.partner"].sudo().search(
        [("id", "=", livreur_id), ("lik_role", "=", "livreur"), ("active", "=", True)],
        limit=1,
    )
    if not livreur:
        raise OrderNotFound("Livreur introuvable")
    employer = livreur.lik_employer_societe_id.id or None
    if employer and employer != sid:
        raise ValueError("Ce livreur est une ressource interne d'une autre societe")
    Link = env["likdelivery.fleet.driver"].sudo()
    existing = Link.search(
        [("societe_id", "=", sid), ("livreur_id", "=", livreur_id)], limit=1
    )
    origin = "internal" if employer == sid else "external"
    if existing:
        existing.write({"is_active": True, "origin": origin})
    else:
        Link.create(
            {
                "societe_id": sid,
                "livreur_id": livreur_id,
                "is_active": True,
                "origin": origin,
            }
        )
    audit_row(
        env, lik_user, "LINK_SOCIETE_LIVREUR", "User", livreur_id,
        {"societe_id": sid, "origin": origin},
    )
    return {
        "message": "Livreur externe ajoute a la flotte" if origin == "external" else "Livreur ajoute a la flotte",
        "origin": origin,
    }


def fleet_unlink(env, lik_user, livreur_id, data=None, args=None):
    """LK-SOC-04 — soft-deactivate; internal resources get deactivated too."""
    sid = _societe_id_for(env, lik_user, data, args)
    link = env["likdelivery.fleet.driver"].sudo().search(
        [("societe_id", "=", sid), ("livreur_id", "=", int(livreur_id))], limit=1
    )
    if not link:
        raise OrderNotFound("Association introuvable")
    link.is_active = False
    liv = link.livreur_id
    if liv and liv.lik_employer_societe_id.id == sid:
        liv.active = False
    audit_row(
        env, lik_user, "UNLINK_SOCIETE_LIVREUR", "User", int(livreur_id),
        {"societe_id": sid},
    )
    return {"message": "Livreur retire de la flotte"}


def fleet_update_livreur(env, lik_user, livreur_id, data):
    """LK-SOC-05 — names only for internals; internal plate cannot be emptied."""
    sid = _societe_id_for(env, lik_user, data)
    link = env["likdelivery.fleet.driver"].sudo().search(
        [("societe_id", "=", sid), ("livreur_id", "=", livreur_id), ("is_active", "=", True)],
        limit=1,
    )
    if not link:
        raise OrderNotFound("Livreur hors flotte")
    liv = link.livreur_id
    if not liv or liv.lik_role != "livreur":
        raise OrderNotFound("Livreur introuvable")
    is_internal_resource = liv.lik_employer_societe_id.id == sid
    if "first_name" in data and is_internal_resource:
        liv.lik_first_name = (data.get("first_name") or "").strip() or None
    if "last_name" in data and is_internal_resource:
        liv.lik_last_name = (data.get("last_name") or "").strip() or None
    if "vehicle_type" in data:
        liv.lik_vehicle_type = (data.get("vehicle_type") or "").strip() or None
    if "license_plate" in data:
        plate = (data.get("license_plate") or "").strip()
        if (link.origin or "external") == "internal" and not plate:
            raise ValueError("Plaque requise pour un livreur interne")
        liv.lik_license_plate = plate or None
    audit_row(
        env, lik_user, "UPDATE_FLEET_LIVREUR", "User", livreur_id,
        {"societe_id": sid},
    )
    out = user_to_dict(_lik_user_for_partner(env, liv.id))
    out["origin"] = link.origin or "external"
    out["is_internal"] = out["origin"] == "internal"
    return {"message": "Livreur mis a jour", "livreur": out}


def societe_orders(env, lik_user, args=None):
    """LK-SOC-06 — E45: preferred orders, status=open or exact filter."""
    sid = lik_user.partner_id.id
    if lik_user.lik_role == "admin" and (args or {}).get("societe_id"):
        sid = int(args["societe_id"])
    domain = [("preferred_societe_id", "=", sid), ("mode", "=", "delivery")]
    status = ((args or {}).get("status") or "").strip()
    if status == "open":
        domain.append(("state", "not in", ["CANCELLED", "DELIVERED", "FAILED"]))
    elif status:
        domain.append(("state", "=", status))
    orders = env["likdelivery.order"].sudo().search(domain, order="create_date desc")
    return [order_to_dict(env, o) for o in orders]
