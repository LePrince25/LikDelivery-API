import base64
import mimetypes
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.http import request

IMAGE_FIELDS = ("favicon", "login_logo", "app_logo")
IMAGE_FALLBACKS = {
    "favicon": ("favicon", "app_logo", "login_logo"),
    "app_logo": ("app_logo", "login_logo", "favicon"),
    "login_logo": ("login_logo", "app_logo", "favicon"),
}
SVG_MIME = "image/svg+xml"
UNSAFE_SVG = re.compile(
    rb"<script|on\w+\s*=|javascript:|xlink:href\s*=\s*['\"]\s*javascript:|<foreignobject",
    re.I,
)


def decode_binary(payload):
    if not payload:
        return b""
    raw = payload if isinstance(payload, bytes) else str(payload).encode()
    stripped = raw.lstrip(b"\xef\xbb\xbf").lstrip()
    if stripped.startswith((b"<", b"\x89PNG", b"\xff\xd8", b"GIF8", b"RIFF")):
        return stripped
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        return stripped


def is_svg_bytes(raw):
    if not raw:
        return False
    text = raw.lstrip(b"\xef\xbb\xbf").lstrip()
    if text.startswith(b"<svg") or text.startswith(b"<?xml"):
        return b"<svg" in text[:4096].lower()
    return False


def svg_is_safe(raw):
    return bool(raw) and not UNSAFE_SVG.search(raw)


class LikosBranding(models.Model):
    _name = "likos.branding"
    _description = "LikOS 19 branding"
    _order = "company_id, id"

    name = fields.Char(default="LikOS", required=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.company,
    )
    favicon = fields.Binary(
        string="Favicon",
        attachment=True,
        help="Icône de l'onglet du navigateur (PNG, SVG, ICO).",
    )
    favicon_filename = fields.Char()
    login_logo = fields.Binary(
        string="Logo de connexion",
        attachment=True,
        help="Logo affiché sur la page de connexion backend (PNG, JPEG, WebP, SVG).",
    )
    login_logo_filename = fields.Char()
    app_logo = fields.Binary(
        string="Logo de l'application",
        attachment=True,
        help="Logo de la barre d'apps et de l'icône PWA (PNG, JPEG, WebP, SVG).",
    )
    app_logo_filename = fields.Char()

    _company_unique = models.Constraint(
        "UNIQUE(company_id)",
        "Each company can only have one LikOS branding.",
    )

    def init(self):
        self._attach_orphan_brandings()
        if self.search([], limit=1):
            self._ensure_company_brandings()

    @api.depends("company_id", "company_id.name", "name")
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.company_id.name or record.name or "LikOS"

    @api.model
    def _attach_orphan_brandings(self):
        orphans = self.search([("company_id", "=", False)])
        if not orphans:
            return
        used = set(self.search([("company_id", "!=", False)]).mapped("company_id").ids)
        companies = self.env["res.company"].sudo().search([])
        main = self.env.ref("base.main_company", raise_if_not_found=False)
        available = companies.filtered(lambda company: company.id not in used)
        if main and main in available:
            available = main | (available - main)
        for branding, company in zip(orphans, available):
            branding.company_id = company.id
            used.add(company.id)
        leftovers = self.search([("company_id", "=", False)])
        if leftovers:
            leftovers.unlink()

    @api.model
    def _ensure_company_brandings(self):
        self._attach_orphan_brandings()
        companies = self.env["res.company"].sudo().search([])
        existing = set(self.search([("company_id", "in", companies.ids)]).mapped("company_id").ids)
        for company in companies:
            if company.id in existing:
                continue
            self.create({
                "name": company.name or "LikOS",
                "company_id": company.id,
            })
            existing.add(company.id)

    @api.model
    def _http_request(self):
        try:
            return request.httprequest
        except (AttributeError, RuntimeError):
            return None

    @api.model
    def _request_hostname(self):
        httprequest = self._http_request()
        if httprequest is None:
            return False
        host = (
            httprequest.headers.get("X-Forwarded-Host")
            or httprequest.headers.get("X-Lbg-Portal")
            or httprequest.headers.get("Host")
            or httprequest.host
        )
        if host and "," in str(host):
            host = str(host).split(",", 1)[0].strip()
        return host or False

    @api.model
    def _company_from_request(self):
        user = self.env.user
        if user and user.id and not user._is_public():
            return self.env.company
        host = self._request_hostname()
        Company = self.env["res.company"].sudo()
        if host and hasattr(Company, "_lbg_from_hostname"):
            company = Company._lbg_from_hostname(host)
            if company:
                return company
        return self.env.company or Company.search([], limit=1)

    @api.model
    def get_for_company(self, company=None):
        company = company or self.env.company
        if not company:
            return self.browse()
        rec = self.search([("company_id", "=", company.id)], limit=1)
        if not rec:
            rec = self.create({"name": company.name or "LikOS", "company_id": company.id})
        return rec

    @api.model
    def get_for_request(self):
        return self.get_for_company(self._company_from_request())

    @api.model
    def get_singleton(self):
        return self.get_for_request()

    @api.model
    def action_open_list(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Logos et icônes",
            "res_model": "likos.branding",
            "view_mode": "list,form",
            "target": "current",
            "context": {"create": False, "delete": False},
        }

    @api.model
    def action_open_settings(self):
        rec = self.get_for_company(self.env.company)
        return {
            "type": "ir.actions.act_window",
            "name": "Logos et icônes",
            "res_model": "likos.branding",
            "res_id": rec.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
            "context": {"create": False, "delete": False},
        }

    def asset_version(self):
        rec = self[:1] or self.get_for_request()
        if rec.write_date:
            return str(int(rec.write_date.timestamp()))
        return "0"

    def resolve_image_field(self, field_name):
        self.ensure_one()
        for name in IMAGE_FALLBACKS.get(field_name, (field_name,)):
            if self[name]:
                return name
        return field_name

    def public_image_mimetype(self, field_name):
        self.ensure_one()
        name = self.resolve_image_field(field_name)
        if self[name]:
            return self.image_mimetype(name)
        return SVG_MIME

    def image_bytes(self, field_name):
        self.ensure_one()
        return decode_binary(self[field_name])

    def is_svg(self, field_name):
        self.ensure_one()
        filename = (self["%s_filename" % field_name] or "").lower()
        if filename.endswith(".svg"):
            return True
        return is_svg_bytes(self.image_bytes(field_name))

    def image_mimetype(self, field_name):
        self.ensure_one()
        filename = self["%s_filename" % field_name] or ""
        if self.is_svg(field_name):
            return SVG_MIME
        guessed, _enc = mimetypes.guess_type(filename)
        if guessed:
            return guessed
        if filename.lower().endswith(".ico"):
            return "image/x-icon"
        if filename.lower().endswith(".webp"):
            return "image/webp"
        raw = self.image_bytes(field_name)
        if raw.startswith(b"\x89PNG"):
            return "image/png"
        if raw.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            return "image/webp"
        if raw.startswith(b"GIF8"):
            return "image/gif"
        return "image/png"

    def _prepare_image_vals(self, vals):
        vals = dict(vals)
        for field_name in IMAGE_FIELDS:
            if field_name not in vals or not vals[field_name]:
                continue
            raw = decode_binary(vals[field_name])
            filename_key = "%s_filename" % field_name
            current = self[:1]
            filename = (vals.get(filename_key) or (current[filename_key] if current else "") or "").lower()
            if is_svg_bytes(raw) or filename.endswith(".svg"):
                raw = raw.lstrip(b"\xef\xbb\xbf").lstrip()
                if not is_svg_bytes(raw) or not svg_is_safe(raw):
                    raise ValidationError(
                        "This SVG is not a safe icon. Remove scripts and event handlers, then upload again."
                    )
                vals[field_name] = base64.b64encode(raw)
                if not vals.get(filename_key):
                    vals[filename_key] = "%s.svg" % field_name.replace("_", "-")
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create([self._prepare_image_vals(vals) for vals in vals_list])
        records._sync_company_logo()
        return records

    def write(self, vals):
        vals = self._prepare_image_vals(vals)
        res = super().write(vals)
        if any(key in vals for key in IMAGE_FIELDS):
            self._sync_company_logo()
        return res

    def _sync_company_logo(self):
        for branding in self:
            if not branding.company_id:
                continue
            field_name = "app_logo" if branding.app_logo else "login_logo"
            logo = branding.app_logo or branding.login_logo
            if not logo or branding.is_svg(field_name):
                continue
            branding.company_id.sudo().write({"logo": logo})

    def action_apply(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }
