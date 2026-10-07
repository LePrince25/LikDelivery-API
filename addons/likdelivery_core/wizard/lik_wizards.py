"""Admin wizards — test notification (send-test equivalent, D7) and manual
dispatch (assign a driver from the back-office)."""

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services import assignment
from ..services.notification import notify


class LikNotificationTest(models.TransientModel):
    _name = "likdelivery.notification.test"
    _description = "Envoyer une notification test"

    lik_user_id = fields.Many2one("likdelivery.user", string="Compte plateforme")
    guest_phone = fields.Char(string="Téléphone invité")
    channel = fields.Selection(
        [("in-app", "In-app"), ("sms", "SMS"), ("whatsapp", "WhatsApp")],
        default="in-app",
        required=True,
    )
    title = fields.Char(default="Test", required=True)
    body = fields.Text(default="Message test", required=True)

    def action_send(self):
        self.ensure_one()
        notify(
            self.env,
            partner=self.lik_user_id.partner_id if self.lik_user_id else None,
            guest_phone=self.guest_phone or None,
            channel=self.channel,
            title=self.title,
            body=self.body,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Notification envoyée"),
                "type": "success",
                "sticky": False,
            },
        }


class LikAssignDriverWizard(models.TransientModel):
    _name = "likdelivery.assign.driver"
    _description = "Assigner un livreur (dispatch admin)"

    order_id = fields.Many2one("likdelivery.order", required=True, readonly=True)
    livreur_id = fields.Many2one(
        "res.partner",
        required=True,
        domain="[('lik_role', '=', 'livreur'), ('active', '=', True)]",
        string="Livreur",
    )

    def action_assign(self):
        self.ensure_one()
        try:
            run = assignment.assign_livreur_to_order(
                self.env,
                self.order_id,
                self.livreur_id,
                {"id": self.env.user.partner_id.id, "role": "admin"},
            )
        except ValueError as err:
            raise UserError(str(err))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Livreur assigné"),
                "message": _("Course #%s créée pour %s", run.id, self.livreur_id.name),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
