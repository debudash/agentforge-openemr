<?php

/**
 * Clinical Co-Pilot Agent tab.
 *
 * Placeholder page the CopilotAgent menu tab opens. The agent itself is built
 * in a later stage against the use cases in USERS.md; this page exists so the
 * tab is wired end to end and shows who is signed in and what their panel is.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

// Locate interface/globals.php by walking up, not by counting levels: this file
// may be reached through a symlink (on Railway the module lives on the sites
// volume), so its real depth in the tree is not fixed.
$openemrRoot = __DIR__;
while (!is_file($openemrRoot . "/interface/globals.php") && dirname($openemrRoot) !== $openemrRoot) {
    $openemrRoot = dirname($openemrRoot);
}
require_once $openemrRoot . "/interface/globals.php";

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Twig\TwigContainer;
use OpenEMR\Core\Header;
use OpenEMR\Services\UserService;

if (!AclMain::aclCheckCore('patients', 'demo')) {
    echo (new TwigContainer(null, $GLOBALS['kernel']))->getTwig()->render(
        'core/unauthorized.html.twig',
        ['pageTitle' => xl("Clinical Co-Pilot")]
    );
    exit;
}

// Note: UserService is used rather than the session wrapper, whose API differs
// between the flex (master) and stable OpenEMR images.
$user = (new UserService())->getCurrentlyLoggedInUser();
$username = $user['username'] ?? '';
$displayName = trim(($user['fname'] ?? '') . ' ' . ($user['lname'] ?? '')) ?: $username;

// The clinician's panel: patients whose assigned provider is this user.
// OpenEMR does not enforce this (AUDIT.md S3) — the agent must filter every
// read to this set, per REQ-SCOPE-1 in USERS.md.
$panelSize = 0;
if (!empty($user['id'])) {
    $row = sqlQuery(
        "SELECT COUNT(*) AS panel FROM patient_data WHERE providerID = ?",
        [$user['id']]
    );
    $panelSize = (int) ($row['panel'] ?? 0);
}
?>
<!DOCTYPE html>
<html>
<head>
    <?php Header::setupHeader(); ?>
    <title><?php echo xlt("Clinical Co-Pilot"); ?></title>
</head>
<body class="body_top container-fluid">
    <h2 class="mt-3"><?php echo xlt("Clinical Co-Pilot"); ?></h2>

    <div class="card mt-3">
        <div class="card-body">
            <p class="mb-1">
                <strong><?php echo xlt("Signed in as"); ?>:</strong>
                <?php echo text($displayName); ?> (<?php echo text($username); ?>)
            </p>
            <p class="mb-1">
                <strong><?php echo xlt("Patients assigned to you"); ?>:</strong>
                <?php echo text((string) $panelSize); ?>
            </p>
            <p class="text-muted mb-0">
                <?php echo xlt("The co-pilot is not built yet. This tab confirms the module is active and shows the panel the agent will be scoped to."); ?>
            </p>
        </div>
    </div>
</body>
</html>
