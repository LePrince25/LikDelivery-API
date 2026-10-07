/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { resConfigEdition } from "@web/webclient/settings_form_view/widgets/res_config_edition";

patch(resConfigEdition.component.prototype, {
    setup() {
        super.setup();
        this.appName = session.likos_branding?.app_name || "LikOS";
    },
});
