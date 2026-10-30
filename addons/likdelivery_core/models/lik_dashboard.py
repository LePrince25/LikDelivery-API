from datetime import timedelta

from odoo import _, api, fields, models

from .lik_user import LIK_ROLES

MONEY_SUFFIX = " FCFA"
THIN_SPACE = "\u202f"

ROLE_LABELS = dict(LIK_ROLES)

# Etats non terminaux : ce qui reste a faire, a distinguer visuellement du
# vert (livre) et du rouge (annule / echoue).
ACTIVE_ORDER_STATES = ("CREATED", "PREPARING", "PICKUP_IN_PROGRESS", "OUT_FOR_DELIVERY")
ACTIVE_RUN_STATES = ("CREATED", "ACCEPTED", "STARTED", "PICKUP_INITIATED", "PICKED_UP", "IN_TRANSIT")

# Les etats d'echec ne font pas partie de la progression affichee : ils
# remplacent le palier courant par une alerte.
DEAD_END_STATES = ("CANCELLED", "FAILED")

STATE_TONES = {
    "DELIVERED": "success",
    "completed": "success",
    "paid": "success",
    "CANCELLED": "danger",
    "FAILED": "danger",
    "failed": "danger",
    "cancelled": "danger",
    "pending": "warning",
    "CREATED": "muted",
}

# Couleur de serie par etat, en noms de tokens : le SCSS les resout, ce modele
# ignore tout du theme. Reflet de STATUS_COLORS cote web.
STATE_COLORS = {
    "CREATED": "warning",
    "PREPARING": "accent2",
    "PICKUP_IN_PROGRESS": "purple",
    "OUT_FOR_DELIVERY": "accent",
    "DELIVERED": "success",
    "CANCELLED": "ink",
    "FAILED": "danger",
    "ACCEPTED": "accent2",
    "STARTED": "purple",
    "PICKUP_INITIATED": "orange",
    "PICKED_UP": "accent",
    "IN_TRANSIT": "accent",
}

# Palette des series et des parts : meme ordre que CATEGORY_COLORS cote web.
CYCLE_COLORS = ("accent", "success", "warning", "purple", "orange", "danger")


class LikDashboard(models.AbstractModel):
    """Donnees du tableau de bord, adaptees au role du compte connecte.

    Modele abstrait : rien n'est stocke, tout est agrege a la volee. Les
    recherches partent de l'environnement de l'utilisateur, donc les regles
    d'enregistrement (ir_rule.xml) decident seules du perimetre visible ; le
    role ne choisit que la mise en scene.
    """

    _name = "likdelivery.dashboard"
    _description = "Tableau de bord Livraison"

    @api.model
    def get_data(self, days=30):
        partner = self.env.user.partner_id
        role = partner.lik_role if partner.lik_role in ROLE_LABELS else "client"
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 30
        if days not in self.PERIODS:
            days = 30
        payload = getattr(self, f"_payload_{role}")(partner, days)
        # Chaque indicateur porte le menu qu'il ouvre ; on ne le resout qu'ici,
        # une seule fois, contre les menus reellement visibles par ce role.
        pages = self._page_actions()
        for stat in payload["stats"]:
            stat["action_id"] = pages.get(stat.pop("menu"))
        payload.update(
            {
                "role": role,
                "role_label": ROLE_LABELS[role],
                "user_name": partner.lik_first_name or partner.name or partner.phone or "",
                "needs_validation": role in ("fournisseur", "societe")
                and not partner.lik_validated_by_admin,
                "days": days,
                "periods": [{"value": period, "label": f"{period} j"} for period in self.PERIODS],
            }
        )
        return payload

    # ---- Pages de destination -------------------------------------------
    def _page_actions(self):
        """xmlid de menu -> id d'action, pour les menus visibles par l'utilisateur.

        load_menus() est l'autorite : il applique deja les groupes du menu et de
        ses parents, donc le ET implicite parent/enfant. Un indicateur dont le
        menu n'est pas visible devient simplement non cliquable, sans que ce
        modele duplique la matrice de droits.
        """
        menus = self.env["ir.ui.menu"].with_user(self.env.uid).load_menus(True)
        pages = {}
        for entry in menus.values():
            xmlid = entry.get("xmlid") or ""
            if not xmlid.startswith("likdelivery_core."):
                continue
            # Une action client ou serveur n'est pas une liste a ouvrir.
            if entry.get("action_model") != "ir.actions.act_window":
                continue
            pages[xmlid.rsplit(".", 1)[-1]] = entry["action_id"]
        return pages

    # ---- Mise en forme --------------------------------------------------
    def _money(self, value):
        return f"{round(value or 0.0):,}".replace(",", THIN_SPACE) + MONEY_SUFFIX

    def _count(self, value):
        return f"{value:,}".replace(",", THIN_SPACE)

    def _date(self, value):
        if not value:
            return "—"
        return fields.Datetime.context_timestamp(self, value).strftime("%d/%m/%Y %H:%M")

    def _stat(self, label, value, hint="", tone="accent", menu=None):
        return {"label": label, "value": value, "hint": hint, "tone": tone, "menu": menu}

    def _kpi(self, label, series=None, value=None, unit=None, hint="", tone="accent", menu=None):
        """Carte KPI de la maquette : valeur, pastille de variation, sparkline.

        La variation se calcule sur la serie de la fenetre affichee, jamais sur
        une valeur aparte : les deux chiffres racontent la meme histoire. Sans
        serie, la carte reste un simple chiffre — un compteur d'instantane
        n'a rien a raconter en courbe.
        """
        return {
            "label": label,
            "value": value if value is not None else self._count(round(sum(series or []))),
            "unit": unit,
            "hint": hint,
            "tone": tone,
            "menu": menu,
            "series": series or None,
            "delta": self._delta(series) if series else None,
        }

    def _cell(self, text, tone=None):
        return {"text": text or "—", "tone": tone}

    def _state_labels(self, model):
        return dict(self.env[model]._fields["state"]._description_selection(self.env))

    def _state_cell(self, model, state):
        labels = self._state_labels(model)
        return self._cell(labels.get(state, state), STATE_TONES.get(state, "warning"))

    def _block(self, title, model, columns, rows, empty):
        return {
            "title": title,
            "model": model,
            "columns": columns,
            "rows": rows,
            "empty": empty,
        }

    def _sum(self, model, domain, field):
        rows = self.env[model]._read_group(domain, [], [f"{field}:sum"])
        return float(rows[0][0]) if rows else 0.0

    def _has(self, group_xmlid):
        return self.env.user.has_group(group_xmlid)

    def _number(self, value):
        """12.4 -> « 12,4 », -25.0 -> « -25 » : pas de decimale inutile."""
        text = f"{float(value):.1f}"
        if text.endswith(".0"):
            text = text[:-2]
        return text.replace(".", ",")

    def _compact(self, value):
        """1 250 000 -> « 1,3 M », 12 400 -> « 12,4 k » ; pour les libelles courts."""
        value = float(value or 0.0)
        if abs(value) >= 1_000_000:
            return self._number(round(value / 100_000) / 10) + " M"
        if abs(value) >= 1_000:
            return self._number(round(value / 100) / 10) + " k"
        return self._count(round(value))

    def _ago(self, stamp):
        """Temps relatif a la francaise : « il y a 2 h », puis la date courte."""
        if not stamp:
            return "—"
        minutes = int((fields.Datetime.now() - stamp).total_seconds() // 60)
        if minutes < 1:
            return _("à l'instant")
        if minutes < 60:
            return _("il y a %d min", minutes)
        if minutes < 24 * 60:
            return _("il y a %d h", minutes // 60)
        if minutes < 7 * 24 * 60:
            return _("il y a %d j", minutes // (60 * 24))
        return fields.Datetime.context_timestamp(self, stamp).strftime("%d/%m")

    # ---- Series ---------------------------------------------------------
    PERIODS = (7, 30, 90)

    def _since(self, days):
        """Plancher de la fenetre, en UTC naive comme `create_date`."""
        return fields.Datetime.to_datetime(fields.Date.context_today(self) - timedelta(days=days - 1))

    def _window_domain(self, days, field="create_date"):
        return [(field, ">=", self._since(days))]

    def _buckets(self, days):
        """Jours de la fenetre observee, du plus ancien au plus recent."""
        today = fields.Date.context_today(self)
        return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]

    def _day_labels(self, days):
        return [day.strftime("%d/%m") for day in self._buckets(days)]

    def _by_day(self, model, domain, field, date_field):
        """`_read_group` par jour -> {date: total}.

        Odoo 19 deprecie `read_group()` : il renvoie des cles « champ:jour »
        tenant une date affiche et un compteur renomme. `_read_group` garde les
        tuples bruts (groupe, agregats), seuls exploitables ici.

        `create_date` est stocke en UTC et le Togo n'a aucun decalage : le jour
        SQL reste le jour vecu. Les enregistrements sans date sont ecartes
        plutot que parques au premier point de la serie.
        """
        aggregates = [f"{field}:sum"] if field else ["__count"]
        totals = {}
        for stamp, value in self.env[model]._read_group(
            domain, [f"{date_field}:day"], aggregates
        ):
            if not stamp:
                continue
            day = stamp.date() if hasattr(stamp, "date") else stamp
            totals[day] = float(value or 0.0)
        return totals

    def _series(self, model, domain, days, field=None, date_field="create_date"):
        """Un point par jour de la fenetre ; un jour vide vaut 0, jamais un trou."""
        totals = self._by_day(model, domain, field, date_field)
        return [float(totals.get(day, 0.0)) for day in self._buckets(days)]

    def _run_series(self, domain, days, field=None):
        """Une course se date a sa livraison, sinon a son retrait, sinon a sa creation.

        Trois `_read_group` plutot qu'un parcours des enregistrements : la serie
        reste cote SQL meme quand le volume grossit.
        """
        totals = {}
        for date_field, guard in (
            ("delivery_time", [("delivery_time", "!=", False)]),
            ("pickup_time", [("delivery_time", "=", False), ("pickup_time", "!=", False)]),
            ("create_date", [("delivery_time", "=", False), ("pickup_time", "=", False)]),
        ):
            totals.update(self._by_day("likdelivery.delivery.run", domain + guard, field, date_field))
        return [float(totals.get(day, 0.0)) for day in self._buckets(days)]

    def _series_from(self, records, get_stamp, get_value, days):
        """Serie batie sur des enregistrements deja charges.

        Utilisee pour les lignes de commande : une ligne n'a pas de date qui
        lui appartient, c'est celle de sa commande.
        """
        totals = {}
        for record in records:
            stamp = get_stamp(record)
            if not stamp:
                continue
            day = stamp.date() if hasattr(stamp, "date") else stamp
            totals[day] = totals.get(day, 0.0) + float(get_value(record) or 0.0)
        return [float(totals.get(day, 0.0)) for day in self._buckets(days)]

    def _window_size(self, days):
        """7 fenetres d'un jour sur une semaine, 5 fenetres egales au dela."""
        count = 7 if days <= 7 else 5
        return count, max(1, round(days / count))

    def _windowed(self, model, domain, field, days, date_field="create_date"):
        """Somme par fenetre, de la plus ancienne a la plus recente."""
        count, size = self._window_size(days)
        totals = self._by_day(model, domain, field, date_field)
        today = fields.Date.context_today(self)
        windows = []
        for index in range(count):
            end = today + timedelta(days=1) - timedelta(days=size * (count - 1 - index))
            start = end - timedelta(days=size)
            windows.append(
                {
                    "label": start.strftime("%d/%m"),
                    "value": float(sum(v for day, v in totals.items() if start <= day < end)),
                }
            )
        return windows

    def _delta(self, series):
        """Variation premiere moitie / seconde moitie de la fenetre, en pastille.

        `None` quand la serie de reference est vide : mieux vaut n'afficher
        aucune variation qu'un +0 % trompeur. Reflet de deltaPill cote web.
        """
        if len(series) < 2:
            return None
        half = len(series) // 2
        left, right = sum(series[:half]), sum(series[half:])
        if not left and not right:
            return None
        if not left:
            return {"direction": "up", "label": _("Nouveau")}
        delta = (right - left) / left * 100
        rounded = round(delta * 10) / 10 if abs(delta) < 10 else round(delta)
        return {
            "direction": "up" if delta > 0.5 else ("down" if delta < -0.5 else "flat"),
            "label": ("+" if delta > 0 else "") + self._number(rounded) + " %",
        }

    def _mix(self, model, domain, states=None):
        """Repartition par etat, dans l'ordre de la selection, part en pourcentage."""
        labels = self._state_labels(model)
        counts = {
            state: int(count)
            for state, count in self.env[model]._read_group(domain, ["state"], ["__count"])
            if state
        }
        total = sum(counts.values()) or 1
        return [
            {
                "label": labels.get(state, state),
                "value": counts[state],
                "pct": round(counts[state] / total * 100),
                "color": STATE_COLORS.get(state, "ink"),
            }
            for state in (states or labels)
            if counts.get(state)
        ]

    def _top(self, records, get_label, get_value, limit=6, formatter=None):
        """Somme par categorie sur un recordset deja filtre par les regles.

        Passe par les enregistrements visibles plutot qu'un read_group direct :
        les regles d'enregistrement restent la seule autorite du perimetre, y
        compris pour un marchand qui ne voit que ses propres lignes.
        """
        totals = {}
        for record in records:
            key = get_label(record) or _("Autre")
            totals[key] = totals.get(key, 0.0) + float(get_value(record) or 0.0)
        grand = sum(totals.values()) or 1.0
        format_value = formatter or self._compact
        return [
            {
                "label": label,
                "value": value,
                "pct": round(value / grand * 100),
                "text": format_value(value),
            }
            for label, value in sorted(totals.items(), key=lambda kv: -kv[1])[:limit]
        ]

    # ---- Panneaux -------------------------------------------------------
    def _area(self, title, subtitle, labels, series):
        return {
            "kind": "area",
            "title": title,
            "subtitle": subtitle,
            "labels": labels,
            "series": [
                {
                    "name": name,
                    "values": values,
                    "color": color or CYCLE_COLORS[index % len(CYCLE_COLORS)],
                    "total": self._compact(sum(values)),
                }
                for index, (name, values, color) in enumerate(series)
            ],
        }

    def _donut(self, title, subtitle, data, center_label, center_value):
        return {
            "kind": "donut",
            "title": title,
            "subtitle": subtitle,
            "data": data,
            "center_label": center_label,
            "center_value": center_value,
        }

    def _allocation(self, title, subtitle, items):
        return {
            "kind": "allocation",
            "title": title,
            "subtitle": subtitle,
            "items": [
                {**item, "color": CYCLE_COLORS[index % len(CYCLE_COLORS)]}
                for index, item in enumerate(items)
            ],
        }

    def _pairs(self, title, subtitle, a_name, a_windows, b_name, b_windows):
        return {
            "kind": "pairs",
            "title": title,
            "subtitle": subtitle,
            "a_name": a_name,
            "b_name": b_name,
            "groups": [
                {"label": a["label"], "a": a["value"], "b": b["value"]}
                for a, b in zip(a_windows, b_windows)
            ],
        }

    def _event(self, title, detail, stamp, tone="accent"):
        return {"title": title, "detail": detail or "", "time": self._ago(stamp), "tone": tone}

    # ---- Progression ----------------------------------------------------
    def _progress(self, model, record, title, code):
        """Etapes parcourues par une commande ou une course, en ordre."""
        labels = self._state_labels(model)
        steps = [
            (state_code, label)
            for state_code, label in labels.items()
            if state_code not in DEAD_END_STATES and state_code != "PICKUP_INITIATED"
        ]
        codes = [state_code for state_code, _label in steps]
        dead_end = record.state in DEAD_END_STATES
        current = codes.index(record.state) if record.state in codes else -1
        return {
            "title": title,
            "code": code,
            "steps": [
                {
                    "label": label,
                    "status": "todo"
                    if dead_end or current < 0
                    else ("done" if i < current else ("current" if i == current else "todo")),
                }
                for i, (_state_code, label) in enumerate(steps)
            ],
            "alert": labels.get(record.state) if dead_end else None,
        }

    # ---- Roles ----------------------------------------------------------
    @api.model
    def _payload_client(self, partner, days):
        Order = self.env["likdelivery.order"]
        domain = [("client_id", "=", partner.id)]
        delivered_domain = domain + [("state", "=", "DELIVERED")]
        since = self._since(days)
        labels = self._state_labels("likdelivery.order")
        mine = Order.search(domain, limit=8, order="id desc")
        active = Order.search(
            domain + [("state", "in", ACTIVE_ORDER_STATES)], limit=1, order="id desc"
        )
        window = [order for order in Order.search(domain) if order.create_date and order.create_date >= since]
        delivered = [order for order in window if order.state == "DELIVERED"]
        in_progress = sum(1 for order in window if order.state in ACTIVE_ORDER_STATES)
        count_series = self._series("likdelivery.order", domain, days)
        spent_series = self._series("likdelivery.order", delivered_domain, days, field="total")
        fee_series = self._series("likdelivery.order", delivered_domain, days, field="delivery_fee")
        basket_series = [
            spent / count if count else 0.0 for spent, count in zip(spent_series, count_series)
        ]
        spent = sum(spent_series)
        stats = [
            self._kpi(
                _("Mes commandes"),
                count_series,
                hint=_("%d en cours", in_progress),
                menu="menu_lik_orders",
            ),
            self._kpi(
                _("Dépensé"),
                spent_series,
                value=self._money(spent),
                hint=_("%d livrées", len(delivered)),
                tone="success",
                menu="menu_lik_payment_transactions",
            ),
            self._kpi(
                _("Panier moyen"),
                basket_series,
                value=self._money(spent / len(delivered) if delivered else 0),
                hint=_("Sur vos commandes livrées"),
                menu="menu_lik_orders",
            ),
            self._kpi(
                _("Frais de livraison"),
                fee_series,
                value=self._money(sum(fee_series)),
                hint=_("Payés au livreur"),
                menu="menu_lik_runs",
            ),
        ]
        charts = [
            self._area(
                _("Mes dépenses"),
                _("Montant réglé et frais de livraison"),
                self._day_labels(days),
                [
                    (_("Commandes livrées"), spent_series, "accent"),
                    (_("Frais de livraison"), fee_series, "warning"),
                ],
            ),
            self._donut(
                _("Où va mon argent"),
                _("%d commandes sur la période", len(window)),
                self._mix("likdelivery.order", domain + self._window_domain(days)),
                _("Commandes"),
                self._count(len(window)),
            ),
            self._allocation(
                _("Où je dépense le plus"),
                _("Commandes livrées par boutique, 6 premières"),
                self._top(
                    delivered,
                    lambda order: order.supplier_id.display_name,
                    lambda order: order.total,
                    formatter=lambda value: self._compact(value) + " FCFA",
                ),
            ),
            self._pairs(
                _("Réglé vs à régler"),
                _("Commandes livrées par fenêtre de temps"),
                _("Réglé"),
                self._windowed(
                    "likdelivery.order",
                    delivered_domain + [("payment_status", "=", "paid")],
                    "total",
                    days,
                ),
                _("À régler"),
                self._windowed(
                    "likdelivery.order",
                    delivered_domain + [("payment_status", "!=", "paid")],
                    "total",
                    days,
                ),
            ),
        ]
        activity = [
            self._event(
                f"{labels.get(order.state, order.state)} · {order.code}",
                f"{order.supplier_id.display_name} · {self._money(order.total)}",
                order.create_date,
                STATE_TONES.get(order.state, "accent"),
            )
            for order in sorted(window, key=lambda o: o.create_date, reverse=True)[:7]
        ]
        rows = [
            {
                "id": order.id,
                "cells": [
                    self._cell(order.code),
                    self._cell(order.supplier_id.display_name),
                    self._state_cell("likdelivery.order", order.state),
                    self._cell(self._money(order.total)),
                    self._cell(self._date(order.create_date)),
                ],
            }
            for order in mine
        ]
        return {
            "subtitle": _(
                "Vos commandes et leur livraison, sur les %d derniers jours.", days
            ),
            "stats": stats,
            "charts": charts,
            "activity": activity,
            "progress": self._progress(
                "likdelivery.order", active, _("Suivi de votre commande"), active.code
            )
            if active
            else None,
            "tables": [
                self._block(
                    _("Mes commandes"),
                    "likdelivery.order",
                    [_("Référence"), _("Fournisseur"), _("Statut"), _("Total"), _("Date")],
                    rows,
                    _("Aucune commande pour le moment."),
                )
            ],
        }

    @api.model
    def _payload_fournisseur(self, partner, days):
        Order = self.env["likdelivery.order"]
        domain = [("supplier_id", "=", partner.id)]
        delivered_domain = domain + [("state", "=", "DELIVERED")]
        since = self._since(days)
        labels = self._state_labels("likdelivery.order")
        to_prepare = Order.search(
            domain + [("state", "in", ("CREATED", "PREPARING"))], limit=8, order="id desc"
        )
        recent = Order.search(domain, limit=8, order="id desc")
        window = [order for order in Order.search(domain) if order.create_date and order.create_date >= since]
        delivered = [order for order in window if order.state == "DELIVERED"]
        lines = [line for order in delivered for line in order.line_ids]
        pending = sum(1 for order in window if order.state in ("CREATED", "PREPARING"))
        received_series = self._series("likdelivery.order", domain, days)
        revenue_series = self._series("likdelivery.order", delivered_domain, days, field="product_total")
        units_series = self._series_from(
            lines, lambda line: line.order_id.create_date, lambda line: line.quantity, days
        )
        basket_series = [
            revenue / count if count else 0.0
            for revenue, count in zip(revenue_series, received_series)
        ]
        revenue = sum(revenue_series)
        stats = [
            self._kpi(
                _("Commandes reçues"),
                received_series,
                hint=_("%d à préparer", pending),
                menu="menu_lik_orders",
            ),
            self._kpi(
                _("Chiffre d'affaires"),
                revenue_series,
                value=self._money(revenue),
                hint=_("%d commandes livrées", len(delivered)),
                tone="success",
                menu="menu_lik_payment_transactions",
            ),
            self._kpi(
                _("Panier moyen"),
                basket_series,
                value=self._money(revenue / len(delivered) if delivered else 0),
                hint=_("Marchandise vendue"),
                menu="menu_lik_orders",
            ),
            self._kpi(
                _("Articles vendus"),
                units_series,
                hint=_("Solde %s", self._money(partner.lik_wallet_available)),
                menu="menu_lik_wallet_withdrawals",
            ),
        ]
        charts = [
            self._area(
                _("Chiffre d'affaires"),
                _("Marchandise des commandes livrées"),
                self._day_labels(days),
                [(_("Ventes"), revenue_series, "accent")],
            ),
            self._donut(
                _("Statut de vos commandes"),
                _("%d commandes sur la période", len(window)),
                self._mix("likdelivery.order", domain + self._window_domain(days)),
                _("Commandes"),
                self._count(len(window)),
            ),
            self._allocation(
                _("Meilleures ventes"),
                _("Montant encaissé par article, 6 premiers"),
                self._top(
                    lines,
                    lambda line: line.product_id.display_name,
                    lambda line: line.quantity * line.unit_price,
                    formatter=lambda value: self._compact(value) + " FCFA",
                ),
            ),
            self._pairs(
                _("Encaissé vs en attente"),
                _("Marchandise livrée par fenêtre de temps"),
                _("Encaissé"),
                self._windowed(
                    "likdelivery.order",
                    delivered_domain + [("payment_status", "=", "paid")],
                    "product_total",
                    days,
                ),
                _("En attente"),
                self._windowed(
                    "likdelivery.order",
                    delivered_domain + [("payment_status", "!=", "paid")],
                    "product_total",
                    days,
                ),
            ),
        ]
        activity = [
            self._event(
                f"{labels.get(order.state, order.state)} · {order.code}",
                f"{order.client_id.display_name} · {self._money(order.product_total)}",
                order.create_date,
                STATE_TONES.get(order.state, "accent"),
            )
            for order in sorted(window, key=lambda o: o.create_date, reverse=True)[:7]
        ]

        def rows(records):
            return [
                {
                    "id": order.id,
                    "cells": [
                        self._cell(order.code),
                        self._cell(order.client_id.display_name),
                        self._state_cell("likdelivery.order", order.state),
                        self._cell(self._money(order.product_total)),
                        self._cell(self._date(order.create_date)),
                    ],
                }
                for order in records
            ]

        columns = [_("Référence"), _("Client"), _("Statut"), _("Marchandise"), _("Date")]
        return {
            "subtitle": _(
                "Les commandes à préparer et l'activité de votre boutique sur les %d derniers jours.",
                days,
            ),
            "stats": stats,
            "charts": charts,
            "activity": activity,
            "progress": None,
            "tables": [
                self._block(
                    _("Commandes à traiter"),
                    "likdelivery.order",
                    columns,
                    rows(to_prepare),
                    _("Rien à préparer : toutes vos commandes sont en route."),
                ),
                self._block(
                    _("Dernières commandes"),
                    "likdelivery.order",
                    columns,
                    rows(recent),
                    _("Aucune commande reçue pour le moment."),
                ),
            ],
        }

    @api.model
    def _payload_livreur(self, partner, days):
        Run = self.env["likdelivery.delivery.run"]
        domain = [("livreur_id", "=", partner.id)]
        delivered_domain = domain + [("state", "=", "DELIVERED")]
        since = self._since(days)
        labels = self._state_labels("likdelivery.delivery.run")
        active = Run.search(domain + [("state", "in", ACTIVE_RUN_STATES)], limit=8, order="id desc")
        recent = Run.search(domain, limit=8, order="id desc")
        window = [run for run in Run.search(domain) if run.create_date and run.create_date >= since]
        delivered = [run for run in window if run.state == "DELIVERED"]
        active_count = sum(1 for run in window if run.state in ACTIVE_RUN_STATES)
        cancelled = sum(1 for run in window if run.state == "CANCELLED")
        gains_series = self._run_series(delivered_domain, days, field="price")
        count_series = self._run_series(delivered_domain, days)
        distance_series = self._run_series(delivered_domain, days, field="distance_km")
        stats = [
            self._kpi(
                _("Courses livrées"),
                count_series,
                hint=_("%d en cours", active_count),
                menu="menu_lik_runs",
            ),
            self._kpi(
                _("Gains"),
                gains_series,
                value=self._money(sum(gains_series)),
                hint=_("Solde %s", self._money(partner.lik_wallet_available)),
                tone="success",
                menu="menu_lik_wallet_withdrawals",
            ),
            self._kpi(
                _("Distance parcourue"),
                distance_series,
                value=self._number(round(sum(distance_series), 1)),
                unit="km",
                hint=_("%d course annulée", cancelled),
                menu="menu_lik_runs",
            ),
            # Aucune page de note : l'indicateur reste un chiffre, pas un acces.
            # C'est une moyenne de vie, pas une serie de la fenetre : pas de sparkline.
            self._kpi(
                _("Note moyenne"),
                value=self._number(partner.lik_average_rating),
                unit="/5",
                hint=_("%d livraisons au total", partner.lik_total_deliveries),
            ),
        ]
        charts = [
            self._area(
                _("Vos gains"),
                _("Tarif encaissé par course livrée"),
                self._day_labels(days),
                [(_("Gains"), gains_series, "accent")],
            ),
            self._donut(
                _("Statut de vos missions"),
                _("%d missions créées sur la période", len(window)),
                self._mix("likdelivery.delivery.run", domain + self._window_domain(days)),
                _("Missions"),
                self._count(len(window)),
            ),
            self._allocation(
                _("Boutiques où je livre"),
                _("Gains cumulés, 6 premières"),
                self._top(
                    [run for run in delivered if run.order_id.supplier_id],
                    lambda run: run.order_id.supplier_id.display_name,
                    lambda run: run.price,
                    formatter=lambda value: self._compact(value) + " FCFA",
                ),
            ),
            self._pairs(
                _("Payé vs à encaisser"),
                _("Courses livrées par fenêtre de temps"),
                _("Payé"),
                self._windowed(
                    "likdelivery.delivery.run",
                    delivered_domain + [("order_id.payment_status", "=", "paid")],
                    "price",
                    days,
                    date_field="delivery_time",
                ),
                _("À encaisser"),
                self._windowed(
                    "likdelivery.delivery.run",
                    delivered_domain + [("order_id.payment_status", "!=", "paid")],
                    "price",
                    days,
                    date_field="delivery_time",
                ),
            ),
        ]
        activity = [
            self._event(
                f"{labels.get(run.state, run.state)} · {run.order_id.code or _('Course directe')}",
                f"{run.pickup_address} → {run.dropoff_address} · {self._money(run.price)}",
                run.delivery_time or run.create_date,
                STATE_TONES.get(run.state, "accent"),
            )
            for run in sorted(window, key=lambda r: r.create_date, reverse=True)[:7]
        ]

        def rows(runs):
            return [
                {
                    "id": run.id,
                    "cells": [
                        self._cell(run.order_id.code or _("Course directe")),
                        self._cell(run.dropoff_address),
                        self._state_cell("likdelivery.delivery.run", run.state),
                        self._cell(self._money(run.price)),
                        self._cell(f"{run.distance_km:.1f} km"),
                    ],
                }
                for run in runs
            ]

        columns = [_("Commande"), _("Dépose"), _("Statut"), _("Tarif"), _("Distance")]
        current = active.sorted("id")[:1]
        return {
            "subtitle": _(
                "Vos missions du moment et vos gains de livraison sur les %d derniers jours.", days
            ),
            "stats": stats,
            "charts": charts,
            "activity": activity,
            "progress": self._progress(
                "likdelivery.delivery.run",
                current,
                _("Suivi de votre course"),
                current.order_id.code or _("Course directe"),
            )
            if current
            else None,
            "tables": [
                self._block(
                    _("Courses en cours"),
                    "likdelivery.delivery.run",
                    columns,
                    rows(active),
                    _("Aucune course en attente."),
                ),
                self._block(
                    _("Dernières courses"),
                    "likdelivery.delivery.run",
                    columns,
                    rows(recent),
                    _("Aucune course assignée pour le moment."),
                ),
            ],
        }

    @api.model
    def _payload_societe(self, partner, days):
        Run = self.env["likdelivery.delivery.run"]
        Fleet = self.env["likdelivery.fleet.driver"]
        domain = [("livreur_id.lik_employer_societe_id", "=", partner.id)]
        delivered_domain = domain + [("state", "=", "DELIVERED")]
        since = self._since(days)
        labels = self._state_labels("likdelivery.delivery.run")
        recent = Run.search(domain, limit=8, order="id desc")
        fleet = Fleet.search([("societe_id", "=", partner.id)])
        window = [run for run in Run.search(domain) if run.create_date and run.create_date >= since]
        delivered = [run for run in window if run.state == "DELIVERED"]
        in_progress = sum(1 for run in window if run.state in ACTIVE_RUN_STATES)
        gains_series = self._run_series(delivered_domain, days, field="price")
        rated = [run.rating for run in delivered if run.rating]
        stats = [
            self._kpi(
                _("Missions"),
                self._series("likdelivery.delivery.run", domain, days),
                hint=_("%d livrées · %d en cours", len(delivered), in_progress),
                menu="menu_lik_runs",
            ),
            self._kpi(
                _("Gains de livraison"),
                gains_series,
                value=self._money(sum(gains_series)),
                hint=_("Panier moyen %s", self._compact(sum(gains_series) / len(delivered) if delivered else 0) + " FCFA"),
                tone="success",
                menu="menu_lik_runs",
            ),
            self._kpi(
                _("Livreurs actifs"),
                value=self._count(sum(1 for driver in fleet if driver.is_active)),
                unit=f"/ {self._count(len(fleet))}",
                hint=_("Comptes rattachés à votre flotte"),
                menu="menu_lik_fleet_drivers",
            ),
            self._kpi(
                _("Note de la flotte"),
                value=self._number(sum(rated) / len(rated)) if rated else "—",
                unit="/5" if rated else None,
                hint=_("%d avis clients sur la période", len(rated)),
            ),
        ]
        charts = [
            self._area(
                _("Gains de livraison"),
                _("Tarif des courses livrées"),
                self._day_labels(days),
                [(_("Gains"), gains_series, "accent")],
            ),
            self._donut(
                _("Missions et statuts"),
                _("%d missions créées sur la période", len(window)),
                self._mix("likdelivery.delivery.run", domain + self._window_domain(days)),
                _("Missions"),
                self._count(len(window)),
            ),
            self._allocation(
                _("Performance par livreur"),
                _("Montant des courses, 6 premiers livreurs"),
                self._top(
                    delivered,
                    lambda run: run.livreur_id.display_name,
                    lambda run: run.price,
                    formatter=lambda value: self._compact(value) + " FCFA",
                ),
            ),
            self._pairs(
                _("Encaissé vs en attente"),
                _("Courses livrées par fenêtre de temps"),
                _("Encaissé"),
                self._windowed(
                    "likdelivery.delivery.run",
                    delivered_domain + [("order_id.payment_status", "=", "paid")],
                    "price",
                    days,
                    date_field="delivery_time",
                ),
                _("En attente"),
                self._windowed(
                    "likdelivery.delivery.run",
                    delivered_domain + [("order_id.payment_status", "!=", "paid")],
                    "price",
                    days,
                    date_field="delivery_time",
                ),
            ),
        ]
        activity = [
            self._event(
                f"{labels.get(run.state, run.state)} · {run.order_id.code or _('Course directe')}",
                f"{run.livreur_id.display_name or _('Sans livreur')} · "
                f"{run.order_id.supplier_id.display_name or _('Marchand')} · {self._money(run.price)}",
                run.delivery_time or run.create_date,
                STATE_TONES.get(run.state, "accent"),
            )
            for run in sorted(window, key=lambda r: r.create_date, reverse=True)[:7]
        ]
        rows = [
            {
                "id": run.id,
                "cells": [
                    self._cell(run.livreur_id.display_name),
                    self._cell(run.dropoff_address),
                    self._state_cell("likdelivery.delivery.run", run.state),
                    self._cell(self._money(run.price)),
                    self._cell(self._date(run.create_date)),
                ],
            }
            for run in recent
        ]
        return {
            "subtitle": _(
                "L'activité de vos livreurs internes sur les %d derniers jours.", days
            ),
            "stats": stats,
            "charts": charts,
            "activity": activity,
            "progress": None,
            "tables": [
                self._block(
                    _("Courses de la flotte"),
                    "likdelivery.delivery.run",
                    [_("Livreur"), _("Dépose"), _("Statut"), _("Tarif"), _("Date")],
                    rows,
                    _("Aucune course pour vos livreurs pour le moment."),
                )
            ],
        }

    @api.model
    def _payload_admin(self, partner, days):
        Order = self.env["likdelivery.order"]
        Run = self.env["likdelivery.delivery.run"]
        delivered_domain = [("state", "=", "DELIVERED")]
        since = self._since(days)
        labels = self._state_labels("likdelivery.order")
        # Une seule lecture : les series viennent de `_read_group`, les agrégats
        # par categorie de ce recordset, deja filtre par les regles d'enregistrement.
        orders = Order.search([])
        window = [order for order in orders if order.create_date and order.create_date >= since]
        delivered = [order for order in window if order.state == "DELIVERED"]
        in_progress = sum(1 for order in window if order.state in ACTIVE_ORDER_STATES)
        revenue_series = self._series("likdelivery.order", delivered_domain, days, field="total")
        count_series = self._series("likdelivery.order", [], days)
        fee_series = self._series("likdelivery.order", delivered_domain, days, field="delivery_fee")
        basket_series = [
            revenue / count if count else 0.0 for revenue, count in zip(revenue_series, count_series)
        ]
        revenue = sum(revenue_series)
        stats = [
            self._kpi(
                _("Commandes"),
                count_series,
                hint=_("%d en cours", in_progress),
                menu="menu_lik_orders",
            ),
            self._kpi(
                _("Chiffre d'affaires"),
                revenue_series,
                value=self._money(revenue),
                hint=_("Panier moyen %s", self._compact(revenue / len(delivered) if delivered else 0)),
                tone="success",
                menu="menu_lik_payment_transactions",
            ),
            self._kpi(
                _("Panier moyen"),
                basket_series,
                value=self._money(revenue / len(delivered) if delivered else 0),
                hint=_("%d commandes livrées", len(delivered)),
                menu="menu_lik_orders",
            ),
            self._kpi(
                _("Courses"),
                self._series("likdelivery.delivery.run", [], days),
                hint=_("%d en transit", Run.search_count([("state", "in", ACTIVE_RUN_STATES)])),
                menu="menu_lik_runs",
            ),
        ]
        charts = [
            self._area(
                _("Trésorerie de la plateforme"),
                _("Encaissements livrés et frais de collecte"),
                self._day_labels(days),
                [
                    (_("Chiffre d'affaires livré"), revenue_series, "accent"),
                    (_("Frais de livraison"), fee_series, "warning"),
                ],
            ),
            self._donut(
                _("Répartition des commandes"),
                _("%d commandes sur la période", len(window)),
                self._mix("likdelivery.order", self._window_domain(days)),
                _("Commandes"),
                self._count(len(window)),
            ),
            self._allocation(
                _("Où va le chiffre d'affaires"),
                _("Commandes livrées par boutique, 6 premières"),
                self._top(
                    delivered,
                    lambda order: order.supplier_id.display_name,
                    lambda order: order.total,
                    formatter=lambda value: self._compact(value) + " FCFA",
                ),
            ),
            self._pairs(
                _("Encaissé vs en attente"),
                _("Paiements à la livraison par fenêtre de temps"),
                _("Encaissé"),
                self._windowed(
                    "likdelivery.order", delivered_domain + [("payment_status", "=", "paid")], "total", days
                ),
                _("En attente"),
                self._windowed(
                    "likdelivery.order",
                    delivered_domain + [("payment_status", "!=", "paid")],
                    "total",
                    days,
                ),
            ),
        ]
        activity = [
            self._event(
                f"{labels.get(order.state, order.state)} · {order.code}",
                f"{order.client_id.display_name} · {order.supplier_id.display_name} · {self._money(order.total)}",
                order.create_date,
                STATE_TONES.get(order.state, "accent"),
            )
            for order in sorted(window, key=lambda o: o.create_date, reverse=True)[:7]
        ]
        kyc_domain = [
            ("lik_validated_by_admin", "=", False),
            ("lik_is_guest", "=", False),
            ("lik_role", "in", ("fournisseur", "societe")),
        ]
        tables = []
        if self._has("likdelivery_core.group_lik_perm_kyc_manage"):
            User = self.env["likdelivery.user"]
            pending = User.search(kyc_domain, limit=8, order="id desc")
            stats.append(
                self._stat(
                    _("KYC en attente"),
                    self._count(User.search_count(kyc_domain)),
                    _("Comptes à valider"),
                    "danger" if pending else "success",
                    menu="menu_lik_pending_kyc",
                )
            )
            tables.append(
                self._block(
                    _("Demandes KYC en attente"),
                    "likdelivery.user",
                    [_("Téléphone"), _("Nom"), _("Société"), _("Rôle"), _("Pièce d'identité")],
                    [
                        {
                            "id": user.id,
                            "cells": [
                                self._cell(user.phone),
                                self._cell(user.name),
                                self._cell(user.lik_company_name),
                                self._cell(ROLE_LABELS.get(user.lik_role, user.lik_role)),
                                self._cell(
                                    _("Déposée") if user.lik_id_document_filename else _("Absente"),
                                    "success" if user.lik_id_document_filename else "danger",
                                ),
                            ],
                        }
                        for user in pending
                    ],
                    _("Aucune demande en attente de validation."),
                )
            )
        if self._has("likdelivery_core.group_lik_perm_finance_view"):
            stats.append(
                self._stat(
                    _("Retraits en attente"),
                    self._money(
                        self._sum("likdelivery.wallet.withdrawal", [("state", "=", "pending")], "amount")
                    ),
                    _("À payer"),
                    "warning",
                    menu="menu_lik_wallet_withdrawals",
                )
            )
        tables.insert(
            0,
            self._block(
                _("Dernières commandes"),
                "likdelivery.order",
                [_("Référence"), _("Client"), _("Fournisseur"), _("Statut"), _("Total")],
                [
                    {
                        "id": order.id,
                        "cells": [
                            self._cell(order.code),
                            self._cell(order.client_id.display_name),
                            self._cell(order.supplier_id.display_name),
                            self._state_cell("likdelivery.order", order.state),
                            self._cell(self._money(order.total)),
                        ],
                    }
                    for order in orders[:8]
                ],
                _("Aucune commande enregistrée."),
            ),
        )
        return {
            "subtitle": _("Vue d'ensemble de la plateforme sur les %d derniers jours.", days),
            "stats": stats,
            "charts": charts,
            "activity": activity,
            "progress": None,
            "tables": tables,
        }
