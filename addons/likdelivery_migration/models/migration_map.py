from odoo import fields, models


class LikMigrationMap(models.Model):
    """Legacy-ID -> Odoo-ID registry (no ID preservation).

    Odoo sequences/ids cannot safely be forced, so every imported record
    gets a fresh id and the (entity, old_id) -> new_id correspondence is
    stored here. All foreign keys are remapped through this table, which
    also makes the import idempotent: already-mapped old ids are skipped.
    """

    _name = "likdelivery.migration.map"
    _description = "Correspondance IDs hérités / Odoo"
    _order = "entity, old_id"

    entity = fields.Char(required=True, index=True)
    old_id = fields.Integer(required=True, index=True)
    new_id = fields.Integer(required=True)

    _entity_old_uniq = models.Constraint(
        "unique(entity, old_id)", "Cet enregistrement hérité est déjà mappé."
    )
