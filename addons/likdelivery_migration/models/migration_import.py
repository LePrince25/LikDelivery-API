import logging
import os
import sqlite3
from datetime import datetime
from types import SimpleNamespace

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Transient per-record runtime state (mapping cache + stats). Odoo 19
# recordsets are slotted and forbid ad-hoc attribute assignment, so the
# ETL working state lives here for the duration of an import/validation.
_RUNTIME = {}

DEFAULT_SQLITE_PATH = "/var/lib/odoo/livraison.db"
CONFIG_PARAM = "likdelivery_migration.sqlite_path"

# Import order respects foreign keys between entities.
ENTITIES = [
    "category",
    "user",
    "opening_hour",
    "product",
    "shop_driver",
    "fleet_driver",
    "order",
    "delivery_run",
    "cart_session",
    "courier_request",
    "cancellation_rule",
    "payment_transaction",
    "notification",
    "driver_location",
    "audit_log",
    "wallet_withdrawal",
]

ENTITY_MODELS = {
    "category": "likdelivery.product.category",
    "user": "res.partner",
    "opening_hour": "likdelivery.opening.hour",
    "product": "likdelivery.product",
    "shop_driver": "likdelivery.shop.driver",
    "fleet_driver": "likdelivery.fleet.driver",
    "order": "likdelivery.order",
    "order_line": "likdelivery.order.line",
    "delivery_run": "likdelivery.delivery.run",
    "cart_session": "likdelivery.cart.session",
    "courier_request": "likdelivery.courier.request",
    "cancellation_rule": "likdelivery.cancellation.rule",
    "payment_transaction": "likdelivery.payment.transaction",
    "notification": "likdelivery.notification",
    "driver_location": "likdelivery.driver.location",
    "audit_log": "likdelivery.audit.log",
    "wallet_withdrawal": "likdelivery.wallet.withdrawal",
}

ENTITY_TABLES = {
    "category": "categories",
    "user": "users",
    "opening_hour": "opening_hours",
    "product": "supplier_products",
    "shop_driver": "supplier_livreurs",
    "fleet_driver": "societe_livreurs",
    "order": "orders",
    "order_line": "order_lines",
    "delivery_run": "delivery_runs",
    "cart_session": "cart_sessions",
    "courier_request": "courier_requests",
    "cancellation_rule": "cancellation_rules",
    "payment_transaction": "payment_transactions",
    "notification": "notifications",
    "driver_location": "livreur_locations",
    "audit_log": "audit_logs",
    "wallet_withdrawal": "wallet_withdrawals",
}


def _time_to_float(value):
    """Convert a SQLAlchemy Time value ('HH:MM:SS[.ffffff]') to float hours."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    hours = int(parts[0]) if len(parts) > 0 else 0
    minutes = int(parts[1]) if len(parts) > 1 else 0
    seconds = float(parts[2]) if len(parts) > 2 else 0.0
    return hours + minutes / 60.0 + seconds / 3600.0


def _parse_datetime(value):
    """Parse a SQLite datetime string ('YYYY-MM-DD HH:MM:SS[.ffffff]')."""
    if not value:
        return False
    if isinstance(value, datetime):
        return fields.Datetime.to_string(value)
    try:
        return fields.Datetime.to_string(datetime.fromisoformat(str(value)))
    except ValueError:
        return False


class LikMigrationImport(models.Model):
    """One-shot ETL from the Flask reference SQLite DB into likdelivery_core."""

    _name = "likdelivery.migration.import"
    _description = "Import de migration Livraison (SQLite hérité)"
    _order = "id desc"

    name = fields.Char(default="Import SQLite hérité", required=True)
    sqlite_path = fields.Char(
        string="Chemin SQLite",
        default=lambda self: self.env["ir.config_parameter"]
        .sudo()
        .get_param(CONFIG_PARAM, DEFAULT_SQLITE_PATH),
        help="Chemin du fichier livraison.db DANS le conteneur web. "
        "Copier le fichier avec `docker cp livraison.db <web>:/var/lib/odoo/livraison.db`.",
    )
    state = fields.Selection(
        [("draft", "Brouillon"), ("running", "En cours"), ("done", "Terminé"), ("failed", "Échoué")],
        default="draft",
        required=True,
    )
    report = fields.Text(string="Rapport de réconciliation", readonly=True)

    @property
    def _rt(self):
        key = self.id or ("new", id(self))
        return _RUNTIME.setdefault(
            key, SimpleNamespace(map={}, stats=self._new_stats())
        )

    @property
    def _map(self):
        return self._rt.map

    @property
    def stats(self):
        return self._rt.stats

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def _load_map(self):
        mapping = {}
        for rec in self.env["likdelivery.migration.map"].sudo().search([]):
            mapping.setdefault(rec.entity, {})[rec.old_id] = rec.new_id
        self._rt.map = mapping

    def _mid(self, entity, old_id):
        if old_id is None:
            return None
        return self._map.get(entity, {}).get(int(old_id))

    def _register_map(self, entity, old_id, new_id):
        Map = self.env["likdelivery.migration.map"].sudo()
        existing = Map.search(
            [("entity", "=", entity), ("old_id", "=", int(old_id))], limit=1
        )
        if existing:
            self._map.setdefault(entity, {})[int(old_id)] = existing.new_id
            return existing.new_id
        Map.create({"entity": entity, "old_id": int(old_id), "new_id": int(new_id)})
        self._map.setdefault(entity, {})[int(old_id)] = int(new_id)
        return int(new_id)

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

    def _connect(self):
        path = self.sqlite_path or DEFAULT_SQLITE_PATH
        if not os.path.exists(path):
            raise UserError(
                _("Fichier SQLite introuvable : %s\nCopiez-le dans le conteneur, ex. :\n"
                  "docker cp livraison.db $(docker compose ps -q web):/var/lib/odoo/livraison.db")
                % path
            )
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def _rows(self, conn, table, where=None, params=()):
        sql = "SELECT * FROM %s" % table
        if where:
            sql += " WHERE " + where
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            _logger.warning("migration: table %s illisible (%s) — ignorée", table, exc)
            return []

    def _scalar(self, conn, sql, params=()):
        try:
            row = conn.execute(sql, params).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Per-row / per-entity runners (savepoints, error collection)
    # ------------------------------------------------------------------

    def _new_stats(self):
        return {
            entity: {"sqlite": 0, "created": 0, "existing": 0, "skipped": 0, "errors": []}
            for entity in list(ENTITIES) + ["order_line"]
        }

    def _each(self, conn, entity, handler, rows=None):
        """Run `handler(row)` for every row of the entity's table.

        Row-level savepoint: a failing row is rolled back and logged, the
        rest of the entity keeps going.
        """
        if rows is None:
            rows = self._rows(conn, ENTITY_TABLES[entity])
        st = self.stats[entity]
        st["sqlite"] = len(rows)
        for row in rows:
            old_id = row["id"]
            if self._mid(entity, old_id):
                st["skipped"] += 1
                continue
            try:
                with self.env.cr.savepoint():
                    handler(row)
            except Exception as exc:  # noqa: BLE001 — collect, never abort
                st["errors"].append("id=%s: %s" % (old_id, exc))
                _logger.exception("migration %s id=%s failed", entity, old_id)

    # ------------------------------------------------------------------
    # Entity importers
    # ------------------------------------------------------------------

    def _import_categories(self, conn):
        Cat = self.env["likdelivery.product.category"].sudo()

        def handler(row):
            existing = Cat.search([("name", "=", row["name"])], limit=1)
            if existing:
                self._register_map("category", row["id"], existing.id)
                self.stats["category"]["existing"] += 1
                return
            rec = Cat.create({"name": row["name"], "icon": row["icon"] or False})
            self._register_map("category", row["id"], rec.id)
            self.stats["category"]["created"] += 1

        self._each(conn, "category", handler)

    def _import_users(self, conn):
        Partner = self.env["res.partner"].sudo()
        LikUser = self.env["likdelivery.user"].sudo()
        rows = self._rows(conn, "users")
        st = self.stats["user"]
        st["sqlite"] = len(rows)

        # Pass 1 — create partners + platform accounts (or reuse by phone).
        for row in rows:
            old_id = row["id"]
            if self._mid("user", old_id):
                st["skipped"] += 1
                continue
            try:
                with self.env.cr.savepoint():
                    existing = LikUser.search([("phone", "=", row["phone"])], limit=1)
                    if existing:
                        # Demo data / previous run: reuse, register mapping.
                        self._register_map("user", old_id, existing.partner_id.id)
                        st["existing"] += 1
                        continue
                    name = (
                        " ".join(
                            p for p in [row["first_name"], row["last_name"]] if p
                        )
                        or row["company_name"]
                        or row["phone"]
                    )
                    partner = Partner.create(
                        {
                            "name": name,
                            "phone": row["phone"],
                            "email": row["email"] or False,
                            "street": row["address"] or False,
                            "partner_latitude": row["latitude"] or 0.0,
                            "partner_longitude": row["longitude"] or 0.0,
                            "lik_role": row["role"] or "client",
                            "lik_first_name": row["first_name"] or False,
                            "lik_last_name": row["last_name"] or False,
                            "lik_company_name": row["company_name"] or False,
                            "lik_validated_by_admin": bool(row["validated_by_admin"]),
                            "lik_vehicle_type": row["vehicle_type"] or False,
                            "lik_license_plate": row["license_plate"] or False,
                            "lik_average_rating": row["average_rating"] or 5.0,
                            "lik_total_deliveries": row["total_deliveries"] or 0,
                        }
                    )
                    LikUser.create(
                        {
                            "partner_id": partner.id,
                            # pbkdf2:sha256 hash copied VERBATIM — stays valid.
                            "lik_password_hash": row["password_hash"] or False,
                            "lik_jwt_jti": False,
                            "lik_is_guest": False,
                        }
                    )
                    self._register_map("user", old_id, partner.id)
                    st["created"] += 1
            except Exception as exc:  # noqa: BLE001 — e.g. duplicate phone
                st["errors"].append("id=%s phone=%s: %s" % (old_id, row["phone"], exc))
                _logger.exception("migration user id=%s failed", old_id)

        # Pass 2 — société FKs (preferred / employer), now all users mapped.
        for row in rows:
            new_id = self._mid("user", row["id"])
            if not new_id:
                continue
            vals = {}
            if row["preferred_societe_id"]:
                target = self._mid("user", row["preferred_societe_id"])
                if target:
                    vals["lik_preferred_societe_id"] = target
            if row["employer_societe_id"]:
                target = self._mid("user", row["employer_societe_id"])
                if target:
                    vals["lik_employer_societe_id"] = target
            if not vals:
                continue
            try:
                with self.env.cr.savepoint():
                    partner = Partner.browse(new_id)
                    # Do not clobber values already set on reused partners.
                    todo = {f: v for f, v in vals.items() if not partner[f]}
                    if todo:
                        partner.write(todo)
            except Exception as exc:  # noqa: BLE001
                st["errors"].append("id=%s FK société: %s" % (row["id"], exc))

    def _import_opening_hours(self, conn):
        Hour = self.env["likdelivery.opening.hour"].sudo()

        def handler(row):
            partner_id = self._mid("user", row["user_id"])
            if not partner_id:
                raise UserError(_("utilisateur hérité %s non mappé") % row["user_id"])
            rec = Hour.create(
                {
                    "partner_id": partner_id,
                    "day_of_week": str(row["day_of_week"]),
                    "open_time": _time_to_float(row["open_time"]),
                    "close_time": _time_to_float(row["close_time"]),
                }
            )
            self._register_map("opening_hour", row["id"], rec.id)
            self.stats["opening_hour"]["created"] += 1

        self._each(conn, "opening_hour", handler)

    def _import_products(self, conn):
        Product = self.env["likdelivery.product"].sudo()

        def handler(row):
            supplier_id = self._mid("user", row["supplier_id"])
            if not supplier_id:
                raise UserError(_("fournisseur hérité %s non mappé") % row["supplier_id"])
            rec = Product.create(
                {
                    "supplier_id": supplier_id,
                    "category_id": self._mid("category", row["category_id"]) or False,
                    "name": row["name"],
                    "description": row["description"] or False,
                    "price": row["price"] or 0.0,
                    "stock": row["stock"] or 0,
                    "active": bool(row["active"]),
                    "fragile": bool(row["fragile"]),
                    "lik_image_url": row["image_url"] or False,
                }
            )
            self._register_map("product", row["id"], rec.id)
            self.stats["product"]["created"] += 1

        self._each(conn, "product", handler)

    def _import_shop_drivers(self, conn):
        Link = self.env["likdelivery.shop.driver"].sudo()

        def handler(row):
            supplier_id = self._mid("user", row["supplier_id"])
            livreur_id = self._mid("user", row["livreur_id"])
            if not supplier_id or not livreur_id:
                raise UserError(_("boutique/livreur non mappé"))
            existing = Link.search(
                [("supplier_id", "=", supplier_id), ("livreur_id", "=", livreur_id)],
                limit=1,
            )
            if existing:
                self._register_map("shop_driver", row["id"], existing.id)
                self.stats["shop_driver"]["existing"] += 1
                return
            rec = Link.create(
                {
                    "supplier_id": supplier_id,
                    "livreur_id": livreur_id,
                    "is_active": bool(row["is_active"]),
                }
            )
            self._register_map("shop_driver", row["id"], rec.id)
            self.stats["shop_driver"]["created"] += 1

        self._each(conn, "shop_driver", handler)

    def _import_fleet_drivers(self, conn):
        Link = self.env["likdelivery.fleet.driver"].sudo()

        def handler(row):
            societe_id = self._mid("user", row["societe_id"])
            livreur_id = self._mid("user", row["livreur_id"])
            if not societe_id or not livreur_id:
                raise UserError(_("société/livreur non mappé"))
            existing = Link.search(
                [("societe_id", "=", societe_id), ("livreur_id", "=", livreur_id)],
                limit=1,
            )
            if existing:
                self._register_map("fleet_driver", row["id"], existing.id)
                self.stats["fleet_driver"]["existing"] += 1
                return
            rec = Link.create(
                {
                    "societe_id": societe_id,
                    "livreur_id": livreur_id,
                    "origin": row["origin"] or "external",
                    "is_active": bool(row["is_active"]),
                }
            )
            self._register_map("fleet_driver", row["id"], rec.id)
            self.stats["fleet_driver"]["created"] += 1

        self._each(conn, "fleet_driver", handler)

    def _import_orders(self, conn):
        Order = self.env["likdelivery.order"].sudo()
        Line = self.env["likdelivery.order.line"].sudo()
        rows = self._rows(conn, "orders")
        st = self.stats["order"]
        st["sqlite"] = len(rows)
        for row in rows:
            old_id = row["id"]
            if self._mid("order", old_id):
                st["skipped"] += 1
                continue
            try:
                with self.env.cr.savepoint():
                    existing = Order.search([("code", "=", row["code"])], limit=1)
                    if existing:
                        self._register_map("order", old_id, existing.id)
                        st["existing"] += 1
                        continue
                    supplier_id = self._mid("user", row["supplier_id"])
                    if not supplier_id:
                        raise UserError(
                            _("fournisseur hérité %s non mappé") % row["supplier_id"]
                        )
                    order = Order.create(
                        {
                            "code": row["code"],
                            "client_id": self._mid("user", row["client_id"]) or False,
                            "guest_phone": row["guest_phone"] or False,
                            "supplier_id": supplier_id,
                            "mode": row["mode"] or "delivery",
                            "state": row["status"] or "CREATED",
                            "delivery_address": row["delivery_address"] or False,
                            "delivery_lat": row["delivery_lat"] or 0.0,
                            "delivery_lon": row["delivery_lon"] or 0.0,
                            "delivery_fee": row["delivery_fee"] or 0.0,
                            "product_total": row["product_total"] or 0.0,
                            "total": row["total"] or 0.0,
                            "payment_method": row["payment_method"] or "cash_on_delivery",
                            "payment_status": row["payment_status"] or "pending",
                            "is_fragile": bool(row["is_fragile"]),
                            "open_for_platform_claim": bool(row["open_for_platform_claim"]),
                            "preferred_societe_id": self._mid(
                                "user", row["preferred_societe_id"]
                            )
                            or False,
                            "supplier_wallet_credited": bool(
                                row["supplier_wallet_credited"]
                            ),
                            "otp_code": row["otp_code"] or False,
                            "rating": row["rating"]
                            if row["rating"] is not None
                            else False,
                            "rating_comment": row["rating_comment"] or False,
                        }
                    )
                    self._register_map("order", old_id, order.id)
                    st["created"] += 1
                    for lrow in self._rows(
                        conn, "order_lines", "order_id = ?", (old_id,)
                    ):
                        self.stats["order_line"]["sqlite"] += 1
                        if self._mid("order_line", lrow["id"]):
                            self.stats["order_line"]["skipped"] += 1
                            continue
                        product_id = self._mid("product", lrow["product_id"])
                        if not product_id:
                            raise UserError(
                                _("produit hérité %s non mappé") % lrow["product_id"]
                            )
                        line = Line.create(
                            {
                                "order_id": order.id,
                                "product_id": product_id,
                                "quantity": lrow["quantity"] or 1,
                                "unit_price": lrow["unit_price"] or 0.0,
                            }
                        )
                        self._register_map("order_line", lrow["id"], line.id)
                        self.stats["order_line"]["created"] += 1
            except Exception as exc:  # noqa: BLE001
                st["errors"].append("id=%s code=%s: %s" % (old_id, row["code"], exc))
                _logger.warning(
                    "migration order id=%s code=%s failed: %s", old_id, row["code"], exc
                )

    def _import_delivery_runs(self, conn):
        Run = self.env["likdelivery.delivery.run"].sudo()

        def handler(row):
            rec = Run.create(
                {
                    "order_id": self._mid("order", row["order_id"]) or False,
                    "standalone": bool(row["standalone"]),
                    "pickup_address": row["pickup_address"] or "-",
                    "pickup_lat": row["pickup_lat"] or 0.0,
                    "pickup_lon": row["pickup_lon"] or 0.0,
                    "dropoff_address": row["dropoff_address"] or "-",
                    "dropoff_lat": row["dropoff_lat"] or 0.0,
                    "dropoff_lon": row["dropoff_lon"] or 0.0,
                    "distance_km": row["distance_km"] or 0.0,
                    "price": row["price"] or 0.0,
                    "state": row["status"] or "CREATED",
                    "livreur_id": self._mid("user", row["livreur_id"]) or False,
                    "source": "plateforme",
                    "otp_code": row["otp_code"] or False,
                    "qr_token": row["qr_token"] or False,
                    "is_fragile": bool(row["is_fragile"]),
                    "pickup_time": _parse_datetime(row["pickup_time"]),
                    "delivery_time": _parse_datetime(row["delivery_time"]),
                    "rating": row["rating"] if row["rating"] is not None else False,
                    "rating_comment": row["rating_comment"] or False,
                }
            )
            self._register_map("delivery_run", row["id"], rec.id)
            self.stats["delivery_run"]["created"] += 1

        self._each(conn, "delivery_run", handler)

    def _import_cart_sessions(self, conn):
        Cart = self.env["likdelivery.cart.session"].sudo()

        def handler(row):
            supplier_id = self._mid("user", row["supplier_id"])
            product_id = self._mid("product", row["product_id"])
            if not supplier_id or not product_id:
                raise UserError(_("fournisseur/produit non mappé"))
            rec = Cart.create(
                {
                    "client_id": self._mid("user", row["client_id"]) or False,
                    "session_token": row["session_token"] or False,
                    "supplier_id": supplier_id,
                    "product_id": product_id,
                    "quantity": row["quantity"] or 1,
                }
            )
            self._register_map("cart_session", row["id"], rec.id)
            self.stats["cart_session"]["created"] += 1

        self._each(conn, "cart_session", handler)

    def _import_courier_requests(self, conn):
        Req = self.env["likdelivery.courier.request"].sudo()

        def handler(row):
            existing = Req.search([("code", "=", row["code"])], limit=1)
            if existing:
                self._register_map("courier_request", row["id"], existing.id)
                self.stats["courier_request"]["existing"] += 1
                return
            rec = Req.create(
                {
                    "code": row["code"],
                    "client_id": self._mid("user", row["client_id"]) or False,
                    "guest_phone": row["guest_phone"] or False,
                    "pickup_address": row["pickup_address"] or "-",
                    "pickup_lat": row["pickup_lat"] or 0.0,
                    "pickup_lon": row["pickup_lon"] or 0.0,
                    "dropoff_address": row["dropoff_address"] or "-",
                    "dropoff_lat": row["dropoff_lat"] or 0.0,
                    "dropoff_lon": row["dropoff_lon"] or 0.0,
                    "distance_km": row["distance_km"] or 0.0,
                    "price": row["price"] or 0.0,
                    "is_fragile": bool(row["is_fragile"]),
                    "payment_method": row["payment_method"] or "cash_on_delivery",
                    "payment_status": row["payment_status"] or "pending",
                    "state": "CREATED",  # reference v1 only has CREATED
                    "livreur_id": self._mid("user", row["livreur_id"]) or False,
                }
            )
            self._register_map("courier_request", row["id"], rec.id)
            self.stats["courier_request"]["created"] += 1

        self._each(conn, "courier_request", handler)

    def _import_cancellation_rules(self, conn):
        Rule = self.env["likdelivery.cancellation.rule"].sudo()

        def handler(row):
            rec = Rule.create(
                {
                    "min_hours": row["min_hours"] or 0,
                    "max_hours": row["max_hours"],
                    "penalty_percent": row["penalty_percent"] or 80.0,
                    "applies_to_paid": bool(row["applies_to_paid"]),
                    "applies_to_cash": bool(row["applies_to_cash"]),
                    "active": bool(row["active"]),
                }
            )
            self._register_map("cancellation_rule", row["id"], rec.id)
            self.stats["cancellation_rule"]["created"] += 1

        self._each(conn, "cancellation_rule", handler)

    def _import_payment_transactions(self, conn):
        Tx = self.env["likdelivery.payment.transaction"].sudo()

        def handler(row):
            existing = Tx.search([("reference", "=", row["reference"])], limit=1)
            if existing:
                self._register_map("payment_transaction", row["id"], existing.id)
                self.stats["payment_transaction"]["existing"] += 1
                return
            target_type = row["target_type"]
            vals = {
                "reference": row["reference"],
                "target_type": target_type,
                "amount": row["amount"] or 0.0,
                "provider": row["provider"],
                "phone": row["phone"] or False,
                "state": row["status"] or "pending",
                "provider_ref": row["provider_ref"] or False,
                "failure_reason": row["failure_reason"] or False,
            }
            if target_type == "order":
                order_id = self._mid("order", row["target_id"])
                if not order_id:
                    raise UserError(
                        _("commande héritée %s non mappée") % row["target_id"]
                    )
                vals["order_id"] = order_id
            elif target_type == "courier":
                req_id = self._mid("courier_request", row["target_id"])
                if not req_id:
                    raise UserError(
                        _("course héritée %s non mappée") % row["target_id"]
                    )
                vals["courier_request_id"] = req_id
            else:
                raise UserError(_("target_type inconnu: %s") % target_type)
            rec = Tx.create(vals)
            self._register_map("payment_transaction", row["id"], rec.id)
            self.stats["payment_transaction"]["created"] += 1

        self._each(conn, "payment_transaction", handler)

    def _import_notifications(self, conn):
        Notif = self.env["likdelivery.notification"].sudo()

        def handler(row):
            rec = Notif.create(
                {
                    "user_id": self._mid("user", row["user_id"]) or False,
                    "guest_phone": row["guest_phone"] or False,
                    "channel": row["channel"] or "in-app",
                    "title": row["title"] or "-",
                    "body": row["body"] or "-",
                    "link": row["link"] or False,
                    "is_read": bool(row["is_read"]),
                }
            )
            self._register_map("notification", row["id"], rec.id)
            self.stats["notification"]["created"] += 1

        self._each(conn, "notification", handler)

    def _import_driver_locations(self, conn):
        Loc = self.env["likdelivery.driver.location"].sudo()

        def handler(row):
            livreur_id = self._mid("user", row["livreur_id"])
            if not livreur_id:
                raise UserError(_("livreur hérité %s non mappé") % row["livreur_id"])
            rec = Loc.create(
                {
                    "livreur_id": livreur_id,
                    "latitude": row["latitude"] or 0.0,
                    "longitude": row["longitude"] or 0.0,
                    "accuracy": row["accuracy"],
                    # recorded_at is a real field: legacy timestamp preserved.
                    "recorded_at": _parse_datetime(row["recorded_at"]) or False,
                }
            )
            self._register_map("driver_location", row["id"], rec.id)
            self.stats["driver_location"]["created"] += 1

        self._each(conn, "driver_location", handler)

    def _import_audit_logs(self, conn):
        Log = self.env["likdelivery.audit.log"].sudo()

        def handler(row):
            details = row["details"] or ""
            if row["created_at"]:
                stamp = "[legacy created_at: %s]" % row["created_at"]
                details = ("%s\n%s" % (details, stamp)).strip()
            rec = Log.create(
                {
                    "actor_id": self._mid("user", row["actor_id"]) or False,
                    "actor_role": row["actor_role"] or False,
                    "action": row["action"] or "UNKNOWN",
                    "target_type": row["target_type"] or False,
                    # target_id stays in the LEGACY id space (see report note).
                    "target_id": row["target_id"],
                    "ip": row["ip"] or False,
                    "details": details or False,
                }
            )
            self._register_map("audit_log", row["id"], rec.id)
            self.stats["audit_log"]["created"] += 1

        self._each(conn, "audit_log", handler)

    def _import_wallet_withdrawals(self, conn):
        Wd = self.env["likdelivery.wallet.withdrawal"].sudo()

        def handler(row):
            user_id = self._mid("user", row["user_id"])
            if not user_id:
                raise UserError(_("utilisateur hérité %s non mappé") % row["user_id"])
            rec = Wd.create(
                {
                    "user_id": user_id,
                    "role": row["role"],
                    "amount": row["amount"] or 0.0,
                    "kind": row["kind"],
                    "state": row["status"] or "completed",
                    "note": row["note"] or False,
                }
            )
            self._register_map("wallet_withdrawal", row["id"], rec.id)
            self.stats["wallet_withdrawal"]["created"] += 1

        self._each(conn, "wallet_withdrawal", handler)

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    def action_run_import(self):
        """Run the full ETL, then the reconciliation report.

        Safe to re-run: already-mapped records are skipped (idempotent).
        """
        self.ensure_one()
        self.write({"state": "running", "report": False})
        self._load_map()
        self._rt.stats = self._new_stats()
        fatal = False
        conn = None
        try:
            conn = self._connect()
        except Exception as exc:  # noqa: BLE001
            fatal = True
            self._rt.fatal_error = str(exc)
        importers = [
            ("category", self._import_categories),
            ("user", self._import_users),
            ("opening_hour", self._import_opening_hours),
            ("product", self._import_products),
            ("shop_driver", self._import_shop_drivers),
            ("fleet_driver", self._import_fleet_drivers),
            ("order", self._import_orders),
            ("delivery_run", self._import_delivery_runs),
            ("cart_session", self._import_cart_sessions),
            ("courier_request", self._import_courier_requests),
            ("cancellation_rule", self._import_cancellation_rules),
            ("payment_transaction", self._import_payment_transactions),
            ("notification", self._import_notifications),
            ("driver_location", self._import_driver_locations),
            ("audit_log", self._import_audit_logs),
            ("wallet_withdrawal", self._import_wallet_withdrawals),
        ]
        entity_aborts = []
        if not fatal:
            for entity, fn in importers:
                try:
                    # Entity-level savepoint: a catastrophic entity failure
                    # rolls back that entity only, the rest keeps going.
                    with self.env.cr.savepoint():
                        fn(conn)
                except Exception as exc:  # noqa: BLE001
                    entity_aborts.append("%s: %s" % (entity, exc))
                    self.stats[entity]["errors"].append("ENTITY ABORTED: %s" % exc)
                    _logger.exception("migration entity %s aborted", entity)
            conn.close()
        report = self._build_report(
            conn_ok=not fatal,
            fatal_error=getattr(self._rt, "fatal_error", None),
            entity_aborts=entity_aborts,
        )
        self.write(
            {
                "state": "failed" if (fatal or entity_aborts) else "done",
                "report": report,
            }
        )
        _logger.info("likdelivery migration report:\n%s", report)
        return True

    def action_validate(self):
        """Recompute the reconciliation report without importing."""
        self.ensure_one()
        self._load_map()
        self._rt.stats = self._new_stats()
        report = self._build_report(conn_ok=True)
        self.report = report
        _logger.info("likdelivery migration validation:\n%s", report)
        return True

    # ------------------------------------------------------------------
    # Reconciliation report
    # ------------------------------------------------------------------

    def _mapped_ids(self, entity):
        return list(self._map.get(entity, {}).values())

    def _build_report(self, conn_ok=True, fatal_error=None, entity_aborts=None):
        lines = []
        add = lines.append
        add("=== RAPPORT DE RÉCONCILIATION MIGRATION LIKDELIVERY ===")
        add("Date: %s" % fields.Datetime.now())
        add("Source SQLite: %s" % (self.sqlite_path or DEFAULT_SQLITE_PATH))
        if fatal_error:
            add("")
            add("ERREUR FATALE: %s" % fatal_error)
            return "\n".join(lines)
        if entity_aborts:
            add("")
            add("ENTITÉS AVORTÉES (rollback complet de l'entité):")
            for e in entity_aborts:
                add("  - %s" % e)

        conn = self._connect() if conn_ok else None
        try:
            # ---- per-entity counts -------------------------------------
            add("")
            add("%-22s %8s %8s %8s %8s %8s %6s" % (
                "entité", "sqlite", "créés", "réutil.", "sautés", "odoo", "err"))
            add("-" * 80)
            for entity in list(ENTITIES) + ["order_line"]:
                table = ENTITY_TABLES[entity]
                sqlite_count = (
                    self._scalar(conn, "SELECT COUNT(*) FROM %s" % table)
                    if conn
                    else self.stats.get(entity, {}).get("sqlite", 0)
                )
                st = self.stats.get(
                    entity, {"created": 0, "existing": 0, "skipped": 0, "errors": []}
                )
                mapped = self._mapped_ids(entity)
                model = ENTITY_MODELS[entity]
                odoo_count = (
                    self.env[model].sudo().browse(mapped).exists().mapped("id")
                )
                add(
                    "%-22s %8s %8s %8s %8s %8s %6s"
                    % (
                        entity,
                        sqlite_count if sqlite_count is not None else "n/a",
                        st["created"],
                        st["existing"],
                        st["skipped"],
                        len(odoo_count),
                        len(st["errors"]),
                    )
                )
            # ---- sums ---------------------------------------------------
            add("")
            add("--- Sommes de contrôle ---")
            self._report_sum(
                add, conn,
                label="Σ orders.total",
                sql="SELECT SUM(total) FROM orders",
                model="likdelivery.order",
                entity="order",
                field="total",
            )
            self._report_sum(
                add, conn,
                label="Σ delivery_runs.price",
                sql="SELECT SUM(price) FROM delivery_runs",
                model="likdelivery.delivery.run",
                entity="delivery_run",
                field="price",
            )
            self._report_sum(
                add, conn,
                label="Σ wallet_withdrawals.amount",
                sql="SELECT SUM(amount) FROM wallet_withdrawals",
                model="likdelivery.wallet.withdrawal",
                entity="wallet_withdrawal",
                field="amount",
            )
            # ---- unique codes -------------------------------------------
            add("")
            add("--- Unicité des codes ---")
            self._report_unique(
                add, conn, "orders", "code", "likdelivery.order", "order", "code"
            )
            self._report_unique(
                add, conn,
                "courier_requests", "code",
                "likdelivery.courier.request", "courier_request", "code",
            )
            self._report_unique(
                add, conn,
                "payment_transactions", "reference",
                "likdelivery.payment.transaction", "payment_transaction", "reference",
            )
            # ---- wallet equality ----------------------------------------
            add("")
            add("--- Portefeuilles (recalcul des deux côtés, données migrées) ---")
            self._report_wallets(add, conn)
            # ---- row errors ----------------------------------------------
            add("")
            add("--- Erreurs par ligne ---")
            any_err = False
            for entity, st in self.stats.items():
                for err in st.get("errors", []):
                    any_err = True
                    add("  [%s] %s" % (entity, err))
            if not any_err:
                add("  (aucune)")
            add("")
            add("Notes:")
            add("  - Les comptes res.users back-office ne sont PAS migrés "
                "(admins compris): seuls res.partner + likdelivery.user sont créés.")
            add("  - Les horodatages created_at hérités ne sont pas portés "
                "(create_date Odoo non inscriptible). Exceptions: "
                "driver_location.recorded_at est préservé, et audit_log.details "
                "porte le timestamp d'origine.")
            add("  - audit_log.target_id reste dans l'espace d'IDs hérité "
                "(colonne Integer brute, comme la référence).")
            add("  - users.balance n'est pas porté: le portefeuille Odoo est "
                "dérivé (courses/commandes livrées - retraits).")
            add("  - id_document / cfe_document (fichiers) ne sont pas migrés: "
                "la référence stocke des chemins locaux introuvables ici.")
        finally:
            if conn:
                conn.close()
        return "\n".join(lines)

    def _report_sum(self, add, conn, label, sql, model, entity, field):
        sqlite_sum = self._scalar(conn, sql) if conn else None
        sqlite_sum = float(sqlite_sum or 0.0)
        recs = self.env[model].sudo().browse(self._mapped_ids(entity)).exists()
        odoo_sum = float(sum(recs.mapped(field)))
        status = "OK" if abs(sqlite_sum - odoo_sum) < 0.01 else "DIFFÉRENCE"
        add("  %-32s sqlite=%12.2f odoo=%12.2f  %s" % (label, sqlite_sum, odoo_sum, status))

    def _report_unique(self, add, conn, table, column, model, entity, field):
        dupes_sqlite = 0
        if conn:
            dupes_sqlite = self._scalar(
                conn,
                "SELECT COUNT(*) FROM (SELECT %s FROM %s GROUP BY %s HAVING COUNT(*) > 1)"
                % (column, table, column),
            ) or 0
        values = (
            self.env[model]
            .sudo()
            .browse(self._mapped_ids(entity))
            .exists()
            .mapped(field)
        )
        seen = set()
        dupes_odoo = len([v for v in values if v in seen or seen.add(v)])
        status = "OK" if (dupes_sqlite == 0 and dupes_odoo == 0) else "DOUBLONS"
        add(
            "  %-28s doublons sqlite=%s odoo=%s  %s"
            % ("%s.%s" % (table, column), dupes_sqlite, dupes_odoo, status)
        )

    def _sqlite_wallet(self, conn, old_user_id, role):
        if role == "livreur":
            earned = self._scalar(
                conn,
                "SELECT SUM(price) FROM delivery_runs WHERE livreur_id = ? AND status = 'DELIVERED'",
                (old_user_id,),
            )
        elif role == "fournisseur":
            earned = self._scalar(
                conn,
                "SELECT SUM(product_total) FROM orders WHERE supplier_id = ? AND status = 'DELIVERED'",
                (old_user_id,),
            )
        else:
            return None
        withdrawn = self._scalar(
            conn,
            "SELECT SUM(amount) FROM wallet_withdrawals WHERE user_id = ? AND status IN ('completed','pending')",
            (old_user_id,),
        )
        earned = float(earned or 0.0)
        withdrawn = float(withdrawn or 0.0)
        return earned, withdrawn, max(0.0, round(earned - withdrawn, 0))

    def _report_wallets(self, add, conn):
        Partner = self.env["res.partner"].sudo()
        checked = mismatches = 0
        for old_id, new_id in sorted(self._map.get("user", {}).items()):
            partner = Partner.browse(new_id).exists()
            if not partner or partner.lik_role not in ("livreur", "fournisseur"):
                continue
            sqlite_wallet = (
                self._sqlite_wallet(conn, old_id, partner.lik_role) if conn else None
            )
            if sqlite_wallet is None:
                continue
            s_earned, s_withdrawn, s_avail = sqlite_wallet
            if partner.lik_role == "livreur":
                runs = (
                    self.env["likdelivery.delivery.run"]
                    .sudo()
                    .browse(self._mapped_ids("delivery_run"))
                    .exists()
                    .filtered(
                        lambda r, p=partner: r.livreur_id == p and r.state == "DELIVERED"
                    )
                )
                o_earned = float(sum(runs.mapped("price")))
            else:
                orders = (
                    self.env["likdelivery.order"]
                    .sudo()
                    .browse(self._mapped_ids("order"))
                    .exists()
                    .filtered(
                        lambda o, p=partner: o.supplier_id == p and o.state == "DELIVERED"
                    )
                )
                o_earned = float(sum(orders.mapped("product_total")))
            withdrawals = (
                self.env["likdelivery.wallet.withdrawal"]
                .sudo()
                .browse(self._mapped_ids("wallet_withdrawal"))
                .exists()
                .filtered(
                    lambda w, p=partner: w.user_id == p
                    and w.state in ("completed", "pending")
                )
            )
            o_withdrawn = float(sum(withdrawals.mapped("amount")))
            o_avail = max(0.0, round(o_earned - o_withdrawn, 0))
            checked += 1
            if abs(s_avail - o_avail) > 0.01:
                mismatches += 1
                add(
                    "  DIFFÉRENCE %s (legacy #%s -> partner #%s): "
                    "sqlite earned=%.2f withdrawn=%.2f dispo=%.2f | "
                    "odoo earned=%.2f withdrawn=%.2f dispo=%.2f"
                    % (
                        partner.display_name,
                        old_id,
                        new_id,
                        s_earned,
                        s_withdrawn,
                        s_avail,
                        o_earned,
                        o_withdrawn,
                        o_avail,
                    )
                )
        add(
            "  %d portefeuilles vérifiés, %d divergence(s)%s"
            % (checked, mismatches, " — OK" if mismatches == 0 else "")
        )
