"""KYC service (E36) — LK-KYC-01. Exact port of main/app.py lines 1371-1403."""

import base64

from .audit import audit_row
from .notification import notify

ALLOWED_KYC_EXT = {"pdf", "png", "jpg", "jpeg"}


def _check_ext(filename, label):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext not in ALLOWED_KYC_EXT:
        raise ValueError(f"Fichier {label} invalide")
    return ext


def upload_kyc(env, lik_user, id_file, cfe_file=None):
    """id_file / cfe_file: (filename, bytes). Re-upload resets admin
    validation for fournisseur/societe (reference behavior)."""
    partner = lik_user.partner_id
    if not id_file or not id_file[0]:
        raise ValueError("Piece d'identite requise")
    _check_ext(id_file[0], "identite")
    vals = {
        "lik_id_document": base64.b64encode(id_file[1]),
        "lik_id_document_filename": id_file[0],
    }
    if cfe_file and cfe_file[0]:
        _check_ext(cfe_file[0], "CFE")
        vals["lik_cfe_document"] = base64.b64encode(cfe_file[1])
        vals["lik_cfe_document_filename"] = cfe_file[0]
    if lik_user.lik_role in ("fournisseur", "societe"):
        vals["lik_validated_by_admin"] = False
    partner.sudo().write(vals)
    audit_row(env, lik_user, "UPLOAD_KYC", "User", lik_user.id)
    notify(
        env,
        partner=partner,
        title="KYC soumis",
        body="Vos pieces KYC ont ete soumises et sont en attente de validation.",
    )
    return {
        "message": "Pieces KYC televersees",
        "id_document": vals["lik_id_document_filename"],
        "cfe_document": vals.get("lik_cfe_document_filename"),
    }
