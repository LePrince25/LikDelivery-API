"""Notification service — in-app rows (LK-NOT-01/02).

Minimal port of the reference notify(); sms/whatsapp channels exist in the
model but stay simulated (only in-app rows are created).
"""


def notify(env, partner=None, guest_phone=None, title=None, body=None, link=None,
           channel="in-app"):
    """Create an in-app notification. Guests are keyed by guest_phone."""
    return env["likdelivery.notification"].sudo().create(
        {
            "user_id": partner.id if partner else None,
            "guest_phone": guest_phone if not partner else None,
            "channel": channel,
            "title": title,
            "body": body,
            "link": link or None,
        }
    )


def list_for(env, lik_user):
    """LK-NOT-01 — own notifications (user_id match, or guest_phone == own
    phone), last 50."""
    partner = lik_user.partner_id
    Notif = env["likdelivery.notification"].sudo()
    rows = Notif.search(
        [
            "|",
            ("user_id", "=", partner.id),
            "&",
            ("user_id", "=", False),
            ("guest_phone", "=", partner.phone),
        ],
        order="create_date desc",
        limit=50,
    )
    return [
        {
            "id": n.id,
            "channel": n.channel,
            "title": n.title,
            "body": n.body,
            "link": n.link,
            "is_read": n.is_read,
            "created_at": n.create_date.isoformat(),
        }
        for n in rows
    ]


def mark_read(env, lik_user, note_id):
    """Ownership-checked; silently succeeds when not found (reference)."""
    partner = lik_user.partner_id
    note = env["likdelivery.notification"].sudo().search(
        [
            ("id", "=", note_id),
            "|",
            ("user_id", "=", partner.id),
            "&",
            ("user_id", "=", False),
            ("guest_phone", "=", partner.phone),
        ],
        limit=1,
    )
    if note:
        note.is_read = True
    return {"message": "Notification lue"}
