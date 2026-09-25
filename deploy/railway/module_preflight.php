<?php

/**
 * Does this OpenEMR support the co-pilot module? Run it ON the deploy target.
 *
 *   .\deploy\railway\preflight_module.ps1     (sends this file and the manifest; runs it as apache)
 *
 * Two live failures motivated this, and neither could be caught by anything in the repository,
 * because the repository is the newer OpenEMR:
 *
 *   - `PatientSessionUtil::getPid()` does not exist in 8.0.0. The Co-Pilot and Demo Data tabs
 *     returned a 500 with an empty body, which renders as a blank panel titled "Unknown".
 *   - `<webroot>/demo/generated` is read-only on the stable image, so document generation died
 *     with "Permission denied" -- and writes there would have vanished on the next redeploy.
 *
 * So this asks the target three kinds of question: do the platform APIs the module calls exist,
 * does the module's own code load and answer, and are the paths it needs actually writable.
 * Reads a dependency manifest on stdin (one `Class` or `Class::method` per line) and exits
 * non-zero if anything fails, so a deploy script can refuse to ship.
 *
 * Run it AS THE WEB SERVER USER. `railway ssh` lands as root, and root can write places
 * apache cannot: run as root this reported the read-only web root as writable and created it,
 * which is worse than not checking, because the module then resolves to a directory it cannot
 * write into. preflight_module.ps1 wraps the call in `su -s /bin/sh apache -c`.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

$_GET['site'] = $argv[1] ?? 'default';

/**
 * `pre` runs before shipping, so the module section describes whatever is installed now -- a
 * failure there is usually the reason you are shipping, and must not block it. Only the platform
 * APIs gate at this point, because those are what the new code will need. `post` runs against
 * what was just installed, and everything gates.
 */
$phase = ($argv[2] ?? 'post') === 'pre' ? 'pre' : 'post';

$ignoreAuth = true;
require_once '/var/www/localhost/htdocs/openemr/interface/globals.php';

$failures = [];
$notes = [];
$checks = 0;

/**
 * @param bool $gating false when a failure is worth printing but must not fail the run: an
 *                     optional dependency the module guards with method_exists(), or anything
 *                     about the currently-installed module during the `pre` phase.
 */
function report(string $what, bool $ok, string $detail = '', bool $gating = true): void
{
    global $failures, $notes, $checks;
    $checks++;
    $verdict = $ok ? 'ok' : ($gating ? 'FAIL' : 'note');
    printf("  %-58s %s%s\n", $what, $verdict, $detail === '' ? '' : "  ($detail)");
    if ($ok) {
        return;
    }
    if ($gating) {
        $failures[] = $what . ($detail === '' ? '' : ": $detail");
    } else {
        $notes[] = $what . ($detail === '' ? '' : ": $detail");
    }
}

// -- 1. the OpenEMR version we are talking to ------------------------------------------------
require_once '/var/www/localhost/htdocs/openemr/version.php';
printf("OpenEMR %s.%s.%s%s on PHP %s  [%s-ship]\n\n", $v_major, $v_minor, $v_patch, $v_tag, PHP_VERSION, $phase);

// -- 2. the platform APIs the module calls ---------------------------------------------------
echo "Platform APIs the module calls\n";
$manifest = array_filter(array_map('trim', explode("\n", (string) stream_get_contents(STDIN))));
if ($manifest === []) {
    report('dependency manifest on stdin', false, 'empty; nothing was checked');
}
foreach ($manifest as $entry) {
    // A leading "?" means the module guards this call with method_exists() and copes without it.
    $optional = str_starts_with($entry, '?');
    $entry = ltrim($entry, '?');

    if (str_contains($entry, '::')) {
        [$class, $method] = explode('::', $entry, 2);
        $ok = (class_exists($class) || interface_exists($class)) && method_exists($class, $method);
        report($entry . '()' . ($optional ? ' [optional]' : ''), $ok, $optional && !$ok ? 'absent; the module has a fallback' : '', !$optional);
    } else {
        report($entry, class_exists($entry) || interface_exists($entry), '', !$optional);
    }
}

// -- 3. the module's own code, on this OpenEMR -----------------------------------------------
echo "\nThe module on this OpenEMR\n";
$ns = 'OpenEMR\\Modules\\CopilotAgent\\';
foreach (['ActivePatient', 'Config', 'ChartReader', 'DocumentWriter', 'DemoDocuments', 'PanelScope'] as $class) {
    report("$ns$class autoloads", class_exists($ns . $class), '', $phase === 'post');
}

// The accessor that broke the tabs. Calling it is the check: 0 is a fine answer on the CLI,
// a fatal is not.
try {
    $pid = ($ns . 'ActivePatient')::pid();
    report('ActivePatient::pid() answers', true, "returned $pid");
} catch (Throwable $e) {
    report('ActivePatient::pid() answers', false, get_class($e) . ': ' . $e->getMessage(), $phase === 'post');
}

// -- 4. configuration ------------------------------------------------------------------------
echo "\nConfiguration\n";
try {
    $config = ($ns . 'Config')::load((string) ($GLOBALS['OE_SITE_DIR'] ?? ''));
    report('agent URL configured', ($config->agentUrl ?? '') !== '', '', $phase === 'post');
    report('shared secret configured', ($config->sharedSecret ?? '') !== '', '', $phase === 'post');
    report('demo tools', true, ($config->demoTools ?? false) ? 'on' : 'off');
} catch (Throwable $e) {
    report('Config::load()', false, get_class($e) . ': ' . $e->getMessage(), $phase === 'post');
}

// -- 5. the paths the module writes to -------------------------------------------------------
// Ask DemoDocuments itself where it would write, rather than repeating its logic here: that is
// the whole point, since the answer differs between a bind-mounted dev stack and a deployed image.
echo "\nWritable paths\n";
try {
    $directory = ($ns . 'DemoDocuments')::resolveDirectory('/var/www/localhost/htdocs/openemr');

    $exists = is_dir($directory);
    $usable = $exists ? is_writable($directory) : @mkdir($directory, 0o775, true);
    report('demo folder is writable', (bool) $usable, $directory, $phase === 'post');
    if (!$exists && $usable) {
        echo "    (created it just now)\n";
    }
} catch (Throwable $e) {
    report('demo folder resolves', false, get_class($e) . ': ' . $e->getMessage(), $phase === 'post');
}

$documents = rtrim((string) ($GLOBALS['OE_SITE_DIR'] ?? ''), '/') . '/documents';
report('documents folder is writable', is_dir($documents) && is_writable($documents), $documents);

// -- verdict ----------------------------------------------------------------------------------
echo "\n";
foreach ($notes as $note) {
    echo "note: $note\n";
}
if ($notes !== [] && $phase === 'pre') {
    echo "  (a note is either the module installed right now or an optional API the module guards;\n";
    echo "   neither blocks a ship -- the new module is checked again once it is installed)\n";
}
if ($failures === []) {
    printf("PREFLIGHT (%s-ship): PASS -- %d checks\n", $phase, $checks);
    exit(0);
}
printf("PREFLIGHT (%s-ship): FAIL\n", $phase);
foreach ($failures as $failure) {
    echo "  - $failure\n";
}
exit(1);
