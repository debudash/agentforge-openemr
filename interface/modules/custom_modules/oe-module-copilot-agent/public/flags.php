<?php

/**
 * Public, PHI-free feature flags for the new patient dashboard (ADR 0006, spec 12.1).
 *
 * The dashboard has no OpenEMR session, so this answers without one. It reads the module's
 * configuration only and returns one boolean: whether the Demo Data tooling is on, so the
 * dashboard links Demo Data only when that page would work. No patient, user or session data.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

$ignoreAuth = true;
$openemrRoot = __DIR__;
while (!is_file($openemrRoot . "/interface/globals.php") && dirname($openemrRoot) !== $openemrRoot) {
    $openemrRoot = dirname($openemrRoot);
}
require_once $openemrRoot . "/interface/globals.php";

use OpenEMR\Core\OEGlobalsBag;
use OpenEMR\Modules\CopilotAgent\Config;

$config = Config::load(OEGlobalsBag::getInstance()->getString('OE_SITE_DIR'));

header('Content-Type: application/json');
header('Cache-Control: no-store');
echo json_encode(['demoTools' => $config->demoTools], JSON_THROW_ON_ERROR);
