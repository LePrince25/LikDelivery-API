from . import controllers
from . import models


def post_init_hook(env):
    """Create safe defaults without replacing a project's existing identity."""
    config = env["ir.config_parameter"].sudo()
    if not (config.get_param("APP_NAME") or "").strip():
        config.set_param("APP_NAME", "LikOS")
    env["likos.branding"].sudo()._ensure_company_brandings()


def uninstall_hook(env):
    """Theme cleanup hook reserved for uninstall-time branding reset."""
    return
