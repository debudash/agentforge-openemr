<?php

/**
 * Clinical Co-Pilot Agent module.
 *
 * Adds a top-level "CopilotAgent" tab to the main menu. The menu entries the
 * listener receives are stdClass objects built from
 * interface/main/tabs/menu/menus/*.json, so a new tab is appended in that same
 * shape rather than by editing the tracked JSON (which would conflict on every
 * merge from OpenEMR master).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

namespace OpenEMR\Modules\CopilotAgent;

use OpenEMR\Menu\MenuEvent;
use stdClass;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

class Bootstrap
{
    public const MODULE_INSTALLATION_PATH = "/interface/modules/custom_modules/oe-module-copilot-agent";

    public const MODULE_NAME = "oe-module-copilot-agent";

    /** Menu target: the iframe tab the main screen opens the URL in. */
    private const MENU_TARGET = "cpa";

    /** Second tab: the admin-only service health view. Its own target so it opens beside the co-pilot. */
    private const HEALTH_TARGET = "cph";

    public function __construct(
        private readonly EventDispatcherInterface $eventDispatcher
    ) {
        // Deliberately no OEGlobalsBag calls here: getWebRoot()/getKernel() exist
        // only on master, and this module must also load on the stable image.
        // Menu URLs are site-root relative, so no web root prefix is needed.
    }

    public function subscribeToEvents(): void
    {
        $this->registerMenuItems();
    }

    public function registerMenuItems(): void
    {
        $this->eventDispatcher->addListener(MenuEvent::MENU_UPDATE, $this->addCopilotMenuItem(...));
    }

    /**
     * Append the CopilotAgent tab, and the admin-only health tab beside it.
     *
     * Appending here rather than editing interface/main/tabs/menu/menus/*.json keeps both tabs
     * out of a tracked file, so neither one conflicts on a merge from OpenEMR master.
     */
    public function addCopilotMenuItem(MenuEvent $event): MenuEvent
    {
        $menu = $event->getMenu();

        foreach ($menu as $menuItem) {
            if (($menuItem->menu_id ?? '') === 'cpa0') {
                // Already added (the event can fire more than once per request).
                return $event;
            }
        }

        $item = new stdClass();
        $item->requirement = 0;
        $item->target = self::MENU_TARGET;
        $item->menu_id = 'cpa0';
        $item->label = xlt("CopilotAgent");
        $item->url = self::MODULE_INSTALLATION_PATH . "/public/index.php";
        $item->children = [];
        // Same ACL as the patient finder: anyone who may read demographics.
        $item->acl_req = ["patients", "demo"];
        $item->global_req = [];

        $menu[] = $item;

        // Service health: operational counters, no clinical content. Administrators only, which is
        // the inverse of the co-pilot itself -- an administrator is denied there by design.
        $health = new stdClass();
        $health->requirement = 0;
        $health->target = self::HEALTH_TARGET;
        $health->menu_id = 'cph0';
        $health->label = xlt("CopilotHealth");
        $health->url = self::MODULE_INSTALLATION_PATH . "/public/metrics.php";
        $health->children = [];
        $health->acl_req = ["admin", "super"];
        $health->global_req = [];

        $menu[] = $health;
        $event->setMenu($menu);

        return $event;
    }
}
