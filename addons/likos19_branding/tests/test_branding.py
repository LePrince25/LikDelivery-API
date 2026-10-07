import base64

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.likos19_branding import post_init_hook


class TestLikOSBranding(TransactionCase):
    def test_default_branding_is_available_without_public_route_write(self):
        branding = self.env.ref("likos19_branding.default_branding")

        self.assertEqual(
            self.env["likos.branding"].sudo().get_singleton(),
            branding,
        )
        self.assertEqual(branding.company_id, self.env.ref("base.main_company"))

    def test_post_init_preserves_existing_app_name(self):
        config = self.env["ir.config_parameter"].sudo()
        config.set_param("APP_NAME", "MorisBox Zena")

        post_init_hook(self.env)

        self.assertEqual(config.get_param("APP_NAME"), "MorisBox Zena")

    def test_svg_logo_mimetype_is_preserved(self):
        branding = self.env.ref("likos19_branding.default_branding")
        branding.write({
            "app_logo": base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
            "app_logo_filename": "morisbox.svg",
        })

        self.assertEqual(
            branding.image_mimetype("app_logo"),
            "image/svg+xml",
        )
        self.assertTrue(branding.is_svg("app_logo"))

    def test_svg_is_detected_without_filename(self):
        branding = self.env.ref("likos19_branding.default_branding")
        svg = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/></svg>"""
        branding.write({
            "login_logo": base64.b64encode(svg),
            "login_logo_filename": False,
        })
        self.assertEqual(branding.login_logo_filename, "login-logo.svg")
        self.assertEqual(branding.image_mimetype("login_logo"), "image/svg+xml")

    def test_unsafe_svg_is_rejected(self):
        branding = self.env.ref("likos19_branding.default_branding")
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
        with self.assertRaises(ValidationError):
            branding.write({
                "favicon": base64.b64encode(svg),
                "favicon_filename": "evil.svg",
            })

    def test_each_company_has_its_own_branding(self):
        main = self.env.ref("base.main_company")
        other = self.env["res.company"].create({"name": "LikOS Brand Co %s" % self.uid})
        main_branding = self.env["likos.branding"].get_for_company(main)
        other_branding = self.env["likos.branding"].get_for_company(other)

        self.assertTrue(other.likos_branding_ids)
        self.assertEqual(other.likos_branding_ids, other_branding)
        self.assertNotEqual(main_branding, other_branding)
        self.assertEqual(main_branding.company_id, main)
        self.assertEqual(other_branding.company_id, other)

        before = main_branding.app_logo
        other_branding.write({
            "app_logo": base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'><circle cx='1' cy='1' r='1'/></svg>"),
            "app_logo_filename": "cnss.svg",
        })
        self.assertTrue(other_branding.app_logo)
        self.assertEqual(main_branding.app_logo, before)
        self.assertNotEqual(other_branding.app_logo, before)
        self.assertEqual(self.env["likos.branding"].get_singleton(), main_branding)

    def test_favicon_falls_back_to_app_logo(self):
        branding = self.env.ref("likos19_branding.default_branding")
        branding.write({
            "favicon": False,
            "app_logo": base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
            "app_logo_filename": "mark.svg",
        })
        self.assertEqual(branding.resolve_image_field("favicon"), "app_logo")
        self.assertEqual(branding.public_image_mimetype("favicon"), "image/svg+xml")
