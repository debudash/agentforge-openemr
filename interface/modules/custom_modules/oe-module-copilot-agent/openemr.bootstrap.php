<?php

/**
 * Clinical Co-Pilot Agent module bootstrap.
 *
 * Loaded by ModulesApplication when the module is active. Registers the
 * namespace and subscribes the module's event listeners.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

use OpenEMR\Core\ModulesClassLoader;
use OpenEMR\Core\OEGlobalsBag;
use OpenEMR\Modules\CopilotAgent\Bootstrap;

// A fatal here takes down every page, because module bootstraps are included by
// globals.php. The OEGlobalsBag API differs between the flex (master) and stable
// images — getProjectDir() exists only on master — so resolve the project root
// from this file's own location and guard the whole bootstrap.
try {
    // Walk up to the OpenEMR root rather than counting levels: the module may be
    // symlinked in from elsewhere (on Railway it lives on the sites volume), so
    // __DIR__'s real depth is not fixed.
    $projectDir = __DIR__;
    while (!is_file($projectDir . '/interface/globals.php') && dirname($projectDir) !== $projectDir) {
        $projectDir = dirname($projectDir);
    }
    if (!is_file($projectDir . '/interface/globals.php')) {
        error_log('oe-module-copilot-agent: could not locate the OpenEMR root; menu tab not registered');
        return;
    }

    $classLoader = new ModulesClassLoader($projectDir);
    $classLoader->registerNamespaceIfNotExists('OpenEMR\\Modules\\CopilotAgent\\', __DIR__ . DIRECTORY_SEPARATOR . 'src');

    // Reaching the kernel differs by image: master exposes OEGlobalsBag::getKernel(),
    // while the stable release only sets $GLOBALS['kernel']. Try both.
    $globalsBag = OEGlobalsBag::getInstance();
    $kernel = method_exists($globalsBag, 'getKernel')
        ? $globalsBag->getKernel()
        : ($GLOBALS['kernel'] ?? null);

    if ($kernel === null) {
        error_log('oe-module-copilot-agent: no kernel available; menu tab not registered');
        return;
    }

    $bootstrap = new Bootstrap($kernel->getEventDispatcher());
    $bootstrap->subscribeToEvents();
} catch (\Throwable $e) {
    // Log and carry on: a broken menu tab must never break the application.
    error_log('oe-module-copilot-agent bootstrap failed: ' . $e->getMessage());
}
