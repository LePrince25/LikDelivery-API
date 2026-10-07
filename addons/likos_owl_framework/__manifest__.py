# -*- coding: utf-8 -*-
# Stub minimal pour permettre l'installation des modules SAGCOP qui dépendent
# de likos_owl_framework. Le sous-module d'origine (LIKDIGITALL/likos-owl-framework)
# n'est pas accessible publiquement (dépôt privé, pas de copie locale ni dans
# l'image Docker liksoft/likos:v19-0-1).
#
# Les composants JS / services Owl référencés par les modules SAGCOP via
# @likos_owl_framework/... resteront indisponibles au runtime : les dashboards
# ne se chargeront pas, mais l'installation Odoo pourra se terminer.
{
    "name": "LikOS OWL Framework (stub)",
    "summary": "Stub technique — voir addons/likos_owl_framework/__manifest__.py",
    "version": "19.0.0.0.0",
    "author": "LIKSOFT",
    "website": "https://www.liksoft.tg",
    "category": "LikOS/Framework",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "likos_owl_framework/static/src/js/likos_owl.js",
            "likos_owl_framework/static/src/js/document_dialog.js",
            "likos_owl_framework/static/src/components/document/likos_document_viewer.js",
            "likos_owl_framework/static/src/xml/likos_owl.xml",
        ],
    },
    "application": False,
    "installable": True,
    "auto_install": False,
}
