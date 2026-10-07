/** @odoo-module **/

/**
 * Stub pour `LikosDocumentDialog` (viewer de documents MinIO).
 * Le vrai composant est fourni par le sous-module LIKDIGITALL/likos-owl-framework
 * qui n'est pas accessible. On expose un Component Owl vide qui s'affiche
 * sans contenu.
 */

import { Component } from "@odoo/owl";

export class LikosDocumentDialog extends Component {
    setup() {
        // Pas de logique — le viewer n'est pas disponible en l'absence du vrai framework.
    }
}
LikosDocumentDialog.template = "likos_owl_framework.LikosDocumentDialog";
LikosDocumentDialog.components = {};
LikosDocumentDialog.props = {
    close: { type: Function, optional: true },
    attachmentId: { type: [Number, String], optional: true },
};
