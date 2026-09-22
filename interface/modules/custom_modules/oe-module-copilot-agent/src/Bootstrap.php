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

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Menu\MenuEvent;
use OpenEMR\Menu\PatientMenuEvent;
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

    /** Menu id of the Co-Pilot entry in the patient record's own navbar (Week 2). */
    private const PATIENT_TAB_ID = "copilot";

    /** Its own tab in the main screen, so opening the co-pilot does not replace the chart view. */
    private const PATIENT_TAB_TARGET = "cpapat";

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
        $this->eventDispatcher->addListener(PatientMenuEvent::MENU_UPDATE, $this->addPatientTab(...));
    }

    /**
     * Append a Co-Pilot tab to the patient record's navbar, beside Dashboard, History and Documents.
     *
     * This is the Week 2 entry point: the page reads the active patient from the session, so the
     * panel check happens server-side against whatever chart OpenEMR has open. `pid` is 'false'
     * because the renderer would otherwise append the pid to the URL, and a pid in the URL is
     * exactly what the page must not trust. PatientMenuRole has already made the standard URLs
     * absolute by the time this fires, so the URL here is given ready to use.
     *
     * Clicking it opens a tab of its own rather than replacing the chart view, so the clinician
     * can read the brief and the chart side by side.
     */
    public function addPatientTab(PatientMenuEvent $event): PatientMenuEvent
    {
        $menu = $event->getMenu();
        if (!is_array($menu)) {
            return $event;
        }
        foreach ($menu as $item) {
            if (($item->menu_id ?? '') === self::PATIENT_TAB_ID) {
                return $event;
            }
        }

        [$isHospitalist] = $this->currentRoles();
        if (!$isHospitalist) {
            return $event;
        }

        // The navbar renderer ignores `target` and emits `on_click` verbatim into the anchor, so
        // opening a tab of our own is the click handler's job. navigateTab reuses the tab when it
        // already exists, which is what makes a second click re-read the chart now in view.
        // Falls back to the plain href wherever the main screen's tab API is absent.
        $page = self::MODULE_INSTALLATION_PATH . "/public/patient.php";
        $openInOwnTab = "if (top.navigateTab) { top.navigateTab(top.webroot_url + '" . $page . "', '"
            . self::PATIENT_TAB_TARGET . "', function () { top.activateTabByName('"
            . self::PATIENT_TAB_TARGET . "', true); }); return false; } top.restoreSession();";

        $tab = new stdClass();
        $tab->requirement = 0;
        $tab->target = self::PATIENT_TAB_TARGET;
        $tab->menu_id = self::PATIENT_TAB_ID;
        $tab->label = xlt("Co-Pilot");
        $tab->url = $page;
        $tab->on_click = $openInOwnTab;
        $tab->pid = 'false';
        $tab->children = [];
        $tab->acl_req = ["patients", "demo"];
        $tab->global_req = [];

        // After Documents when it is there, so the tab sits with the chart's own record views.
        $position = count($menu);
        foreach ($menu as $index => $item) {
            if (($item->menu_id ?? '') === 'documents') {
                $position = $index + 1;
                break;
            }
        }
        array_splice($menu, $position, 0, [$tab]);
        $event->setMenu($menu);

        return $event;
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
            if (in_array($menuItem->menu_id ?? '', ['cpa0', 'cph0'], true)) {
                // Already added (the event can fire more than once per request).
                return $event;
            }
        }

        [$isHospitalist, $isAdministrator] = $this->currentRoles();

        // Offered to hospitalists only. `acl_req` cannot express this: AclMain grants a superuser
        // every ACL, so no value would exclude an administrator -- who is refused by the page
        // itself, and would otherwise be shown a tab that only produces an audited denial.
        if ($isHospitalist) {
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
        }

        // Service health: operational counters, no clinical content. Administrators only, which is
        // the inverse of the co-pilot itself.
        if ($isAdministrator) {
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
        }

        $event->setMenu($menu);

        return $event;
    }

    /**
     * Which tabs the signed-in user should be offered.
     *
     * Both pages enforce their own access, so this only decides what is shown. A throwable here
     * would break every page in OpenEMR, menus being built inside globals.php, so a failure hides
     * both tabs rather than propagating.
     *
     * @return array{0: bool, 1: bool} [is a hospitalist, is an administrator]
     */
    private function currentRoles(): array
    {
        try {
            $isAdministrator = AclMain::aclCheckCore('admin', 'super');
            [$isHospitalist] = PanelScope::forCurrentUser()->isHospitalist();
            return [(bool) $isHospitalist, (bool) $isAdministrator];
        } catch (\Throwable $e) {
            return [false, false];
        }
    }
}
