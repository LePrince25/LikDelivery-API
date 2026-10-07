from odoo import fields, models


class LikNotification(models.Model):
    """M14 — notifications table (LK-NOT-01).

    In-app rows; channel supports in-app/sms/whatsapp but only in-app is
    used by the reference (sms/whatsapp simulated). Guests keyed by
    guest_phone.
    """

    _name = "likdelivery.notification"
    _description = "Notification Livraison"
    _order = "id desc"

    user_id = fields.Many2one("res.partner", index=True)
    guest_phone = fields.Char(index=True)
    channel = fields.Selection(
        [("in-app", "In-app"), ("sms", "SMS"), ("whatsapp", "WhatsApp")],
        default="in-app",
        required=True,
    )
    title = fields.Char(required=True)
    body = fields.Text(required=True)
    link = fields.Char()
    is_read = fields.Boolean(default=False, index=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
