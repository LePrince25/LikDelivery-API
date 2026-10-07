/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { UserMenu } from "@web/webclient/user_menu/user_menu";

const VISIBLE_USER_MENU_ITEMS = new Set(["preferences", "logout"]);

patch(UserMenu.prototype, {
    getElements() {
        return super
            .getElements(...arguments)
            .filter((item) => VISIBLE_USER_MENU_ITEMS.has(item.id))
            .map((item) =>
                item.id === "preferences"
                    ? { ...item, description: _t("Profile"), sequence: 10 }
                    : { ...item, sequence: 20 }
            );
    },
});
