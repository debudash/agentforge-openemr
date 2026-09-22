<?php

/**
 * Demo Data tab: generate synthetic documents for validating the Week 2 ingestion flow.
 *
 * NOT PRODUCTION CODE. Renders nothing unless COPILOT_DEMO_TOOLS is set; the actions behind it
 * refuse independently, so hiding the tab is never the only control. Removing this file, the
 * registration block in Bootstrap and the action block in api.php removes the feature.
 *
 * It writes files to a folder. It does not put anything into a chart: the clinician uploads one
 * through OpenEMR's own Documents tab, which is the ingestion path being validated.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

$openemrRoot = __DIR__;
while (!is_file($openemrRoot . "/interface/globals.php") && dirname($openemrRoot) !== $openemrRoot) {
    $openemrRoot = dirname($openemrRoot);
}
require_once $openemrRoot . "/interface/globals.php";

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Logging\EventAuditLogger;
use OpenEMR\Common\Session\PatientSessionUtil;
use OpenEMR\Common\Twig\TwigContainer;
use OpenEMR\Core\Header;
use OpenEMR\Modules\CopilotAgent\Config;
use OpenEMR\Modules\CopilotAgent\DemoDocuments;
use OpenEMR\Modules\CopilotAgent\PanelScope;

if (!AclMain::aclCheckCore('patients', 'demo')) {
    echo (new TwigContainer(null, $GLOBALS['kernel']))->getTwig()->render(
        'core/unauthorized.html.twig',
        ['pageTitle' => xl("Demo Data")]
    );
    exit;
}

$csrf = hash_hmac('sha256', 'copilot', (string) ($_SESSION['csrf_private_key'] ?? session_id()));
$authGroup = (string) ($_SESSION['authProvider'] ?? '');
$pid = PatientSessionUtil::getPid();
$correlationId = bin2hex(random_bytes(8));

$scope = PanelScope::forCurrentUser();
[$isHospitalist, $roleReason] = $scope->isHospitalist();
$config = Config::load((string) ($GLOBALS['OE_SITE_DIR'] ?? ''));

$gate = 'ok';
if (!$config->demoTools) {
    $gate = 'disabled';
} elseif (!$isHospitalist) {
    $gate = 'role';
    EventAuditLogger::getInstance()->newEvent('copilot-role-denied', $scope->username(), $authGroup, 0,
        'cid=' . $correlationId . ' entry=demo ' . $roleReason);
} elseif ($pid <= 0) {
    $gate = 'no_patient';
} elseif (!$scope->isInScope($pid)) {
    $gate = 'scope';
    EventAuditLogger::getInstance()->newEvent('copilot-scope-denied', $scope->username(), $authGroup, 0,
        'cid=' . $correlationId . ' entry=demo', $pid);
}

$patientName = '';
if ($gate === 'ok') {
    $row = QueryUtils::fetchRecords('SELECT fname, lname FROM patient_data WHERE pid = ?', [$pid]);
    $patientName = trim((string) (($row[0]['fname'] ?? '') . ' ' . ($row[0]['lname'] ?? '')));
}
$folder = $config->demoTools ? (new DemoDocuments($scope, $openemrRoot))->directory() : '';
?>
<!DOCTYPE html>
<html>
<head>
    <?php Header::setupHeader(); ?>
    <title><?php echo xlt("Demo Data"); ?></title>
    <style>
        .cpa-warn { border: 2px dashed #b26a00; background: #fff8e6; border-radius: .3rem; padding: .6rem .8rem; }
        .cpa-meta { font-size: .8rem; color: #555; }
        .cpa-path { font-family: monospace; font-size: .8rem; background: #eef1f4; border: 1px solid #d5dbe0;
                    border-radius: .2rem; padding: .1rem .3rem; user-select: all; word-break: break-all; }
        .cpa-step { margin-bottom: .35rem; }
        .cpa-files td { font-size: .85rem; vertical-align: middle; }
        .cpa-out { white-space: pre-wrap; font-family: monospace; font-size: .78rem; }
    </style>
</head>
<body class="body_top container-fluid">
<?php if ($gate === 'disabled') : ?>
    <div class="alert alert-secondary mt-3" role="alert">
        <strong><?php echo xlt("Not enabled."); ?></strong>
        <?php echo xlt("This is validation tooling and is off unless COPILOT_DEMO_TOOLS is set for this instance."); ?>
    </div>
<?php elseif ($gate === 'role') : ?>
    <div class="alert alert-danger mt-3" role="alert"><?php echo text($roleReason); ?></div>
<?php elseif ($gate === 'no_patient') : ?>
    <div class="alert alert-info mt-3" role="alert"><?php echo xlt("Open a patient first."); ?></div>
<?php elseif ($gate === 'scope') : ?>
    <div class="alert alert-danger mt-3" role="alert"><?php echo xlt("This patient is not in your panel."); ?></div>
<?php else : ?>
    <div class="d-flex flex-wrap align-items-center justify-content-between mt-2">
        <h2 class="mb-0"><?php echo xlt("Demo Data"); ?></h2>
        <div class="cpa-warn">
            <strong><?php echo xlt("Validation tooling, not a product feature."); ?></strong>
            <?php echo xlt("It generates synthetic documents so the ingestion flow can be exercised without a real PDF. It is removed before production."); ?>
        </div>
    </div>
    <p class="cpa-meta mt-1 mb-3">
        <?php echo xlt("Patient"); ?>: <strong><?php echo text($patientName); ?></strong> &middot; pid <?php echo text((string) $pid); ?>
        &middot; <?php echo xlt("Documents are written for this patient, so the names on them match the chart."); ?>
    </p>

    <div class="card">
        <div class="card-body">
            <h5><?php echo xlt("1. Generate"); ?></h5>
            <p class="cpa-meta mb-2">
                <?php echo xlt("Writes one lab report and one intake form to the folder below. Nothing is added to the chart: that happens when you upload one, which is the flow being tested."); ?>
            </p>
            <form id="cpa-gen-form" class="form-inline">
                <label for="cpa-variant" class="mr-2"><?php echo xlt("Lab report"); ?></label>
                <select id="cpa-variant" class="form-control mr-2">
                    <option value="abnormal"><?php echo xlt("Abnormal (potassium 5.4, eGFR 58, A1c 7.4)"); ?></option>
                    <option value="normal"><?php echo xlt("Normal (nothing to flag)"); ?></option>
                    <option value="unreadable"><?php echo xlt("Unreadable (no text on the page)"); ?></option>
                    <option value="wrong_patient"><?php echo xlt("Another patient's report (must be refused, not filed)"); ?></option>
                </select>
                <button type="submit" class="btn btn-primary mr-2" id="cpa-gen"><?php echo xlt("Generate New Docs"); ?></button>
                <button type="button" class="btn btn-outline-danger" id="cpa-purge"><?php echo xlt("Purge Docs"); ?></button>
            </form>
            <div class="cpa-meta mt-2">
                <?php echo xlt("Folder"); ?>: <span class="cpa-path"><?php echo text($folder); ?></span>
            </div>
            <div class="cpa-out mt-2" id="cpa-out" aria-live="polite"></div>
        </div>
        <div class="card-body border-top">
            <h5><?php echo xlt("2. Upload one through the chart"); ?></h5>
            <div class="cpa-step">
                <?php echo xlt("Patient record"); ?> &rarr; <strong><?php echo xlt("Documents"); ?></strong> &rarr;
                <?php echo xlt("upload the lab report into category"); ?> <strong><?php echo xlt("Lab Report"); ?></strong>,
                <?php echo xlt("and the intake form into"); ?> <strong><?php echo xlt("Medical Record"); ?></strong>.
            </div>
            <div class="cpa-meta">
                <?php echo xlt("On this machine the files are already in the folder above, so the file picker can reach them. On a deployment, download them first."); ?>
                <?php echo xlt("Do not rename them: Purge recognises them by their name."); ?>
            </div>
            <table class="table table-sm mt-2 cpa-files" id="cpa-files">
                <caption class="sr-only"><?php echo xlt("Generated documents"); ?></caption>
                <thead><tr>
                    <th><?php echo xlt("File"); ?></th><th><?php echo xlt("Size"); ?></th>
                    <th><?php echo xlt("Generated"); ?></th><th></th>
                </tr></thead>
                <tbody></tbody>
            </table>
        </div>
        <div class="card-body border-top">
            <h5><?php echo xlt("3. Run the co-pilot"); ?></h5>
            <div class="cpa-step">
                <?php echo xlt("Open the"); ?> <strong><?php echo xlt("Co-Pilot"); ?></strong>
                <?php echo xlt("tab. It finds the unread document, reads it, has the results filed, and shows what changed with a citation into the page it read."); ?>
            </div>
            <div class="cpa-meta">
                <?php echo xlt("Purge removes the generated files, the documents uploaded from them, and the lab rows those documents produced -- so a citation never outlives the page it points at. It never touches anything it did not generate."); ?>
            </div>
        </div>
    </div>

<script>
(function () {
    "use strict";
    var API = "api.php";
    var PID = <?php echo (int) $pid; ?>;
    var CSRF = <?php echo json_encode($csrf); ?>;
    var out = document.getElementById("cpa-out");

    function api(action, body) {
        return fetch(API + "?action=" + encodeURIComponent(action) + "&context=patient", {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-Copilot-Csrf": CSRF },
            body: JSON.stringify(body || {})
        }).then(function (r) { return r.json().then(function (j) { j.http_status = r.status; return j; }); });
    }

    function say(text, bad) {
        out.textContent = text;
        out.style.color = bad ? "#b71c1c" : "#1b5e20";
    }

    function renderFiles(files) {
        var body = document.querySelector("#cpa-files tbody");
        body.innerHTML = "";
        if (!files || !files.length) {
            var empty = document.createElement("tr");
            var cell = document.createElement("td");
            cell.colSpan = 4; cell.className = "text-muted";
            cell.textContent = "Nothing generated yet.";
            empty.appendChild(cell); body.appendChild(empty); return;
        }
        files.forEach(function (f) {
            var tr = document.createElement("tr");
            ["name", "bytes", "modified"].forEach(function (key) {
                var td = document.createElement("td");
                td.textContent = key === "bytes" ? (f.bytes + " B") : f[key];
                tr.appendChild(td);
            });
            var td = document.createElement("td");
            var a = document.createElement("a");
            a.className = "btn btn-sm btn-outline-secondary";
            a.href = API + "?action=demo_file&context=patient&pid=" + PID + "&name=" + encodeURIComponent(f.name);
            a.textContent = "Download";
            td.appendChild(a); tr.appendChild(td);
            body.appendChild(tr);
        });
    }

    document.getElementById("cpa-gen-form").addEventListener("submit", function (e) {
        e.preventDefault();
        var button = document.getElementById("cpa-gen");
        button.disabled = true; say("Generating…");
        api("demo_generate", { pid: PID, variant: document.getElementById("cpa-variant").value })
            .then(function (res) {
                if (res.http_status !== 200) { say(res.reason || "could not generate", true); return; }
                say("Wrote " + res.generated.map(function (g) { return g.name; }).join(" and ") + ".");
                renderFiles(res.files);
            })
            .catch(function () { say("request failed", true); })
            .then(function () { button.disabled = false; });
    });

    document.getElementById("cpa-purge").addEventListener("click", function () {
        if (!window.confirm("Delete the generated files, the documents uploaded from them, and the lab results read from those documents?")) {
            return;
        }
        var button = document.getElementById("cpa-purge");
        button.disabled = true; say("Purging…");
        api("demo_purge", { pid: PID })
            .then(function (res) {
                if (res.http_status !== 200) { say(res.reason || "could not purge", true); return; }
                say("Removed " + res.files + " file(s), " + res.documents + " document(s) and " + res.results + " lab result(s).");
                renderFiles(res.files_remaining);
            })
            .catch(function () { say("request failed", true); })
            .then(function () { button.disabled = false; });
    });

    api("demo_files", { pid: PID }).then(function (res) { renderFiles(res.files); });
})();
</script>
<?php endif; ?>
</body>
</html>
