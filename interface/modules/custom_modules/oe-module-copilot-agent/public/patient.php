<?php

/**
 * Co-Pilot tab inside the patient record (Week 2 entry point).
 *
 * The patient comes from the session, the way every other tab in the record works, never
 * from a query parameter. OpenEMR will open any chart for any user (AUDIT.md S3), so the
 * panel check here is the only thing between a hospitalist and a patient outside their
 * panel. A refusal is written to the audit log before anything is rendered.
 *
 * The Week 1 tab (index.php) is unchanged and remains the rounding-list entry point.
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
use OpenEMR\Modules\CopilotAgent\PanelScope;

if (!AclMain::aclCheckCore('patients', 'demo')) {
    echo (new TwigContainer(null, $GLOBALS['kernel']))->getTwig()->render(
        'core/unauthorized.html.twig',
        ['pageTitle' => xl("Clinical Co-Pilot")]
    );
    exit;
}

// Same token derivation as index.php and api.php; session access stays at this entry point.
$csrf = hash_hmac('sha256', 'copilot', (string) ($_SESSION['csrf_private_key'] ?? session_id()));
$authGroup = (string) ($_SESSION['authProvider'] ?? '');
$pid = PatientSessionUtil::getPid();
$correlationId = sprintf(
    '%s-%s-4%s-%s-%s',
    bin2hex(random_bytes(4)),
    bin2hex(random_bytes(2)),
    substr(bin2hex(random_bytes(2)), 1),
    dechex(0x8 | (random_int(0, 3))) . substr(bin2hex(random_bytes(2)), 1),
    bin2hex(random_bytes(6))
);

function auditPage(string $event, string $username, string $group, string $comment, ?int $pid = null): void
{
    // Fail closed: a refusal that cannot be recorded is not rendered either.
    EventAuditLogger::getInstance()->newEvent($event, $username, $group, 0, $comment, $pid);
}

$scope = PanelScope::forCurrentUser();
[$isHospitalist, $roleReason] = $scope->isHospitalist();
$config = Config::load((string) ($GLOBALS['OE_SITE_DIR'] ?? ''));

// Exactly one of these renders. Order matters: role before patient, patient before scope.
$gate = 'ok';
if (!$isHospitalist) {
    $gate = 'role';
    auditPage('copilot-role-denied', $scope->username(), $authGroup, 'cid=' . $correlationId . ' entry=patient ' . $roleReason);
} elseif ($pid <= 0) {
    $gate = 'no_patient';
} elseif (!$scope->isInScope($pid)) {
    $gate = 'scope';
    auditPage('copilot-scope-denied', $scope->username(), $authGroup, 'cid=' . $correlationId . ' entry=patient', $pid);
} elseif (!$config->isConfigured()) {
    $gate = 'config';
}

$patientName = '';
if ($gate === 'ok') {
    $row = QueryUtils::fetchRecords('SELECT fname, lname FROM patient_data WHERE pid = ?', [$pid]);
    $patientName = trim(preg_replace('/\d+/', '', (string) (($row[0]['fname'] ?? '') . ' ' . ($row[0]['lname'] ?? ''))));
}
?>
<!DOCTYPE html>
<html>
<head>
    <?php Header::setupHeader(); ?>
    <title><?php echo xlt("Clinical Co-Pilot"); ?></title>
    <style>
        .cpa-state { font-weight: 600; }
        .cpa-state[data-state="complete"] { color: #1b5e20; }
        .cpa-state[data-state="partial"] { color: #8a6d00; }
        .cpa-state[data-state="unable_to_answer"] { color: #b71c1c; }
        .cpa-state[data-state="access_denied"] { color: #b71c1c; }
        .cpa-cite { font-size: .8rem; margin-left: .3rem; }
        .cpa-claim { margin-bottom: .35rem; }
        .cpa-evidence { background: #f7f7f7; border-left: 3px solid #999; padding: .4rem .6rem; font-size: .85rem; margin: .3rem 0 .6rem; }
        .cpa-page-wrap { position: relative; display: inline-block; max-width: 100%; border: 1px solid #c9d1d9; margin-top: .4rem; }
        .cpa-page-wrap img { display: block; max-width: 100%; height: auto; }
        .cpa-box { position: absolute; border: 2px solid #d32f2f; background: rgba(211, 47, 47, .12); box-sizing: border-box; pointer-events: none; }
        .cpa-page-flag { color: #8a6d00; }
        .cpa-source-head { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem; font-size: .85rem; }
        .cpa-evidence-block { border: 1px dashed #7b8a99; border-radius: .3rem; padding: .4rem .6rem; margin-top: .5rem; background: #fbfcfe; }
        .cpa-evidence-title { font-size: .75rem; color: #4a5a6a; text-transform: uppercase; letter-spacing: .05em; margin-bottom: .3rem; }
        .cpa-chat { max-height: 45vh; overflow-y: auto; }
        .cpa-turn-q { background: #eef3ff; }
        .cpa-turn-a { background: #f3fff3; }
        .cpa-turn { padding: .5rem .75rem; border-radius: .4rem; margin-bottom: .5rem; }
        .cpa-meta { font-size: .78rem; color: #555; }
        .cpa-trace { display: inline-flex; align-items: center; gap: .3rem; font-size: .75rem; }
        .cpa-trace-label { color: #666; text-transform: uppercase; letter-spacing: .05em; }
        .cpa-trace-id { background: #eef1f4; border: 1px solid #d5dbe0; border-radius: .2rem;
                        padding: .05rem .3rem; user-select: all; font-size: .75rem; color: #222; white-space: nowrap; }
        .cpa-trace-copy { border: 1px solid #d5dbe0; background: #fff; border-radius: .2rem;
                          font-size: .7rem; padding: 0 .3rem; cursor: pointer; color: #333; }
        .cpa-trace-copy:hover { background: #eef1f4; }
        .cpa-runinfo { font-size: .78rem; color: #555; margin-bottom: .4rem; }
        .cpa-fb { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem; font-size: .75rem; color: #555; }
        .cpa-fb-btn { border: 1px solid #d5dbe0; background: #fff; border-radius: .2rem;
                      font-size: .72rem; padding: .05rem .4rem; cursor: pointer; color: #333; }
        .cpa-fb-btn:hover { background: #eef1f4; }
        .cpa-rule-flag { color: #8a6d00; font-weight: 600; }
        .cpa-rule-engine_failure, .cpa-rule-unable_to_evaluate { color: #b71c1c; }
        .cpa-disclaimer { font-size: .85rem; }
    </style>
</head>
<body class="body_top container-fluid">
    <div class="d-flex flex-wrap align-items-center justify-content-between mt-2">
        <h2 class="mb-0"><?php echo xlt("Clinical Co-Pilot"); ?></h2>
        <div class="cpa-disclaimer alert alert-warning py-1 px-2 mb-0" role="note">
            <?php echo xlt("Demo data only. Not clinically validated for patient care. The clinician reviews the chart and makes every decision."); ?>
        </div>
    </div>
    <p class="cpa-meta mt-1 mb-2">
        <strong><?php echo xlt("Signed in as"); ?>:</strong> <?php echo text($scope->displayName()); ?> (<?php echo text($scope->username()); ?>)
        &middot; <strong><?php echo xlt("Role"); ?>:</strong>
        <?php echo $isHospitalist ? xlt("Hospitalist (Physicians group)") : xlt("not supported"); ?>
    </p>

<?php if ($gate === 'role') : ?>
    <div class="alert alert-danger" role="alert">
        <strong><?php echo xlt("Access denied."); ?></strong>
        <?php echo text($roleReason); ?>.
        <?php echo xlt("The co-pilot is available to providers in the Physicians group only. This denial has been recorded."); ?>
    </div>
<?php elseif ($gate === 'no_patient') : ?>
    <div class="alert alert-info" role="status">
        <strong><?php echo xlt("No patient selected."); ?></strong>
        <?php echo xlt("Open a patient record first. The co-pilot reads the patient from the chart you have open, never from the address bar."); ?>
    </div>
<?php elseif ($gate === 'scope') : ?>
    <div class="alert alert-danger" role="alert">
        <strong><?php echo xlt("Access denied."); ?></strong>
        <?php echo xlt("This patient is not assigned to you, so the co-pilot will not read this chart. This denial has been recorded."); ?>
    </div>
<?php elseif ($gate === 'config') : ?>
    <div class="alert alert-danger" role="alert">
        <strong><?php echo xlt("Not configured."); ?></strong>
        <?php echo xlt("Set COPILOT_AGENT_URL and COPILOT_SHARED_SECRET (environment or sites/<site>/copilot-config.php)."); ?>
    </div>
<?php else : ?>
    <div class="card" id="cpa-patient">
        <div class="card-header py-2">
            <div class="d-flex flex-wrap justify-content-between align-items-center">
                <div>
                    <strong id="cpa-patient-name"><?php echo text($patientName); ?></strong>
                    <span class="cpa-meta" id="cpa-patient-ids"> &middot; pid <?php echo text((string) $pid); ?></span>
                </div>
                <div class="d-flex align-items-center" style="gap:.6rem">
                    <span class="cpa-state" id="cpa-brief-state" data-state=""><?php echo xlt("Reading chart…"); ?></span>
                    <span id="cpa-brief-trace"></span>
                </div>
            </div>
            <div class="cpa-meta" id="cpa-brief-reason"></div>
        </div>
        <div class="card-body cpa-changes" id="cpa-changes" hidden></div>
        <div class="card-body" id="cpa-brief"></div>
        <div class="card-body border-top">
            <details>
                <summary><?php echo xlt("Run details, routing, constraint checks and data sources"); ?></summary>
                <div class="cpa-runinfo mt-2" id="cpa-brief-window"></div>
                <table class="table table-sm mt-2" id="cpa-handoffs"><caption class="sr-only"><?php echo xlt("Supervisor routing"); ?></caption>
                    <thead><tr><th><?php echo xlt("Handoff"); ?></th><th><?php echo xlt("Reason"); ?></th><th><?php echo xlt("Time"); ?></th></tr></thead><tbody></tbody></table>
                <table class="table table-sm mt-2" id="cpa-rules"><caption class="sr-only"><?php echo xlt("Rule engine outcomes"); ?></caption>
                    <thead><tr><th><?php echo xlt("Rule"); ?></th><th><?php echo xlt("Outcome"); ?></th><th><?php echo xlt("Detail"); ?></th></tr></thead><tbody></tbody></table>
                <div class="cpa-meta" id="cpa-sources"></div>
                <div class="cpa-meta" id="cpa-removed"></div>
            </details>
        </div>
        <div class="card-body border-top cpa-source" id="cpa-source" hidden></div>
        <div class="card-body border-top">
            <h5><?php echo xlt("Follow-up questions"); ?></h5>
            <div class="cpa-chat" id="cpa-chat" aria-live="polite"></div>
            <form id="cpa-ask-form" class="form-inline mt-2">
                <label for="cpa-question" class="sr-only"><?php echo xlt("Question about this patient"); ?></label>
                <input type="text" class="form-control mr-2 flex-grow-1" id="cpa-question" maxlength="2000" autocomplete="off"
                       placeholder="<?php echo xla("e.g. What was the last potassium? Any medication past its end date?"); ?>">
                <button type="submit" class="btn btn-primary" id="cpa-ask-btn" disabled><?php echo xlt("Ask"); ?></button>
            </form>
        </div>
    </div>

<script>
(function () {
    "use strict";
    var API = "api.php";
    var CONTEXT = "patient";
    var PID = <?php echo (int) $pid; ?>;
    var CSRF = <?php echo json_encode($csrf); ?>;
    var state = { ready: false };

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) { node.className = cls; }
        if (text !== undefined && text !== null) { node.textContent = String(text); }
        return node;
    }
    function api(action, body) {
        var options = { credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Copilot-Csrf": CSRF } };
        if (body) { options.method = "POST"; options.body = JSON.stringify(body); }
        return fetch(API + "?action=" + encodeURIComponent(action) + "&context=" + CONTEXT, options).then(function (r) {
            return r.json().then(function (j) { j.http_status = r.status; return j; });
        });
    }
    function selectText(node) {
        var range = document.createRange(); range.selectNodeContents(node);
        var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    }
    function traceChip(res) {
        var wrap = el("span", "cpa-trace");
        wrap.appendChild(el("span", "cpa-trace-label", "trace"));
        var full = res.correlation_id || "-";
        var id = el("code", "cpa-trace-id", full.length > 10 ? full.slice(0, 8) + "…" : full);
        id.title = full + (res.langsmith_run_id ? " — LangSmith run " + res.langsmith_run_id : "");
        wrap.appendChild(id);
        var btn = el("button", "cpa-trace-copy", "copy"); btn.type = "button";
        btn.setAttribute("aria-label", "Copy the correlation id for this response");
        btn.addEventListener("click", function () {
            var text = res.correlation_id || "";
            if (res.langsmith_run_id) { text += " langsmith:" + res.langsmith_run_id; }
            var done = function () { btn.textContent = "copied"; setTimeout(function () { btn.textContent = "copy"; }, 1500); };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(done, function () { selectText(id); });
            } else { selectText(id); }
        });
        wrap.appendChild(btn);
        return wrap;
    }
    function stateLabel(s) {
        return { complete: "Complete for requested scope", partial: "Partial", unable_to_answer: "Unable to answer", access_denied: "Access denied" }[s] || s;
    }
    function setState(text, dataState) {
        var st = document.getElementById("cpa-brief-state");
        st.textContent = text; st.setAttribute("data-state", dataState || "");
    }

    // ---- brief -------------------------------------------------------------
    function citeChips(sourceIds, citations, container) {
        sourceIds.forEach(function (sid) {
            var c = citations[sid];
            var chip = el("button", "badge badge-light border cpa-cite", c ? (c.type + " · " + (c.date || "")) : sid);
            chip.type = "button"; chip.title = c ? c.label : sid; chip.setAttribute("aria-label", "Show evidence " + sid);
            chip.addEventListener("click", function () {
                if (c && sourceDocument(c)) { openSource(c); return; }
                var next = chip.parentNode.querySelector(".cpa-evidence[data-sid='" + sid + "']");
                if (next) { next.remove(); return; }
                var box = el("div", "cpa-evidence"); box.setAttribute("data-sid", sid);
                box.appendChild(el("div", "", (c ? c.type + " " : "") + sid + (c && c.date ? " · " + c.date : "")));
                box.appendChild(el("div", "", c ? c.label : "record not in the citation list"));
                chip.parentNode.appendChild(box);
            });
            container.appendChild(chip);
        });
    }
    // Click-to-source: a citation that names a stored document (a document citation, or a lab row
    // read from one) opens that page with the quoted text boxed where the PDF's text layer puts it.
    function sourceDocument(c) {
        if (c.source_type === "document" && c.source_id.indexOf("doc:") === 0) { return parseInt(c.source_id.slice(4), 10); }
        if (c.field_or_chunk_id && c.field_or_chunk_id.indexOf("doc:") === 0) { return parseInt(c.field_or_chunk_id.slice(4), 10); }
        return null;
    }
    function openSource(c) {
        var docId = sourceDocument(c);
        var page = parseInt(String(c.page_or_section || "p1").replace(/^p/, ""), 10) || 1;
        var quote = c.quote_or_value || "";
        var panel = document.getElementById("cpa-source"); panel.hidden = false; panel.innerHTML = "";
        panel.appendChild(el("div", "cpa-meta", "Loading page " + page + " of document " + docId + "…"));
        api("page", { pid: PID, doc_id: docId, page: page, quotes: quote ? [quote] : [] }).then(function (res) {
            panel.innerHTML = "";
            if (res.http_status !== 200) { panel.appendChild(el("div", "text-danger", "Source page unavailable: " + (res.reason || ""))); return; }
            var head = el("div", "cpa-source-head");
            head.appendChild(el("strong", "", "Source: " + (c.label || c.source_id) + " · page " + res.page + " of " + res.pages));
            var link = el("a", "ml-2", "Open original"); link.href = res.original_url; link.target = "_blank"; link.rel = "noopener"; head.appendChild(link);
            var close = el("button", "cpa-fb-btn ml-2", "close"); close.type = "button";
            close.addEventListener("click", function () { panel.hidden = true; panel.innerHTML = ""; }); head.appendChild(close);
            panel.appendChild(head);
            var found = (res.boxes || []).filter(function (b) { return b.found; });
            if (quote && !found.length) {
                panel.appendChild(el("div", "cpa-meta cpa-page-flag", "The quoted text was not located on this page (no text layer, or a scan); the page is shown without a box."));
            }
            var wrap = el("div", "cpa-page-wrap");
            var img = document.createElement("img"); img.src = "data:image/png;base64," + res.image_base64; img.alt = "Document page " + res.page; wrap.appendChild(img);
            found.forEach(function (b) {
                var box = el("div", "cpa-box"); var bb = b.bbox;
                box.style.left = (bb[0] * 100) + "%"; box.style.top = (bb[1] * 100) + "%";
                box.style.width = ((bb[2] - bb[0]) * 100) + "%"; box.style.height = ((bb[3] - bb[1]) * 100) + "%";
                box.title = b.quote; wrap.appendChild(box);
            });
            panel.appendChild(wrap);
            panel.scrollIntoView({ block: "nearest" });
        });
    }
    function renderClaims(claims, citations, container) {
        claims.forEach(function (claim) {
            var row = el("div", "cpa-claim"); row.appendChild(el("span", "", claim.text)); citeChips(claim.source_ids, citations, row); container.appendChild(row);
        });
    }
    function citationMap(list) { var m = {}; (list || []).forEach(function (c) { m[c.source_id] = c; }); return m; }
    function renderBrief(brief) {
        var box = document.getElementById("cpa-brief"); box.innerHTML = "";
        setState(stateLabel(brief.state), brief.state);
        document.getElementById("cpa-brief-window").textContent = "Comparison window: " + brief.comparison_window
            + " · chart read " + brief.generated_at + " · brief " + brief.duration_ms + " ms"
            + " · correlation " + brief.correlation_id
            + (brief.langsmith_run_id ? " · langsmith run " + brief.langsmith_run_id : "");
        var traceBox = document.getElementById("cpa-brief-trace");
        traceBox.textContent = ""; traceBox.appendChild(traceChip(brief));
        document.getElementById("cpa-brief-reason").textContent = brief.state === "complete" ? "" : (brief.state_reason || "");
        var cites = citationMap(brief.citations);
        (brief.sections || []).forEach(function (section) {
            box.appendChild(el("h5", "mt-2", section.title));
            if (!section.claims.length && !section.missing) { box.appendChild(el("div", "text-muted", "Nothing recorded for this section.")); }
            renderClaims(section.claims, cites, box);
            if (section.missing) { box.appendChild(el("div", "text-muted", section.missing)); }
        });
        var rules = document.querySelector("#cpa-rules tbody"); rules.innerHTML = "";
        (brief.rule_outcomes || []).forEach(function (r) {
            var tr = el("tr"); tr.appendChild(el("td", "", r.rule_id + " (" + r.rule_version + ")"));
            tr.appendChild(el("td", "cpa-rule-" + r.outcome, r.outcome.replace(/_/g, " "))); tr.appendChild(el("td", "", r.summary)); rules.appendChild(tr);
        });
        var src = document.getElementById("cpa-sources"); src.textContent = "Sources: " + Object.keys(brief.sources || {}).map(function (k) {
            var s = brief.sources[k]; return k + " " + s.status + " (" + s.count + ", " + s.ms + " ms)"; }).join(" · ");
        var removed = document.getElementById("cpa-removed");
        removed.textContent = (brief.removed_claims || []).length ? (brief.removed_claims.length + " unverified statement(s) were removed by the verifier: "
            + brief.removed_claims.map(function (r) { return r.reason; }).join("; ")) : "All displayed statements passed verification.";
        state.ready = true;
        document.getElementById("cpa-ask-btn").disabled = false;
    }

    // The brief is generated in the background once the session is open; poll select until it is ready.
    function waitForBrief() {
        api("select", { pid: PID }).then(function (res) {
            if (res.http_status !== 200 || res.status === "denied") {
                setState(stateLabel(res.state || "access_denied"), res.state || "access_denied");
                document.getElementById("cpa-brief-reason").textContent = res.reason || (res.brief && res.brief.state_reason) || ""; return;
            }
            if (res.status === "ready" && res.brief) { renderBrief(res.brief); return; }
            if (res.status === "failed") {
                setState(stateLabel("unable_to_answer"), "unable_to_answer");
                document.getElementById("cpa-brief-reason").textContent = res.error || "brief generation failed"; return;
            }
            setState("Brief is being prepared…", "");
            setTimeout(waitForBrief, 2000);
        });
    }
    // Week 2: the supervisor runs on open. It checks for unread documents, reads them, has them
    // persisted, and returns the brief plus what changed. If it cannot run, the Week 1 path
    // (wait for the prefetched brief) still works.
    function renderChanges(res) {
        var box = document.getElementById("cpa-changes"); box.innerHTML = ""; box.hidden = true;
        var docs = res.documents || [];
        var head = el("div", "cpa-meta", docs.length + " document(s) on file" + (res.failed && res.failed.length ? " · " + res.failed.length + " could not be read" : ""));
        if (res.changes && res.changes.length) {
            box.hidden = false;
            box.appendChild(el("h5", "mt-2", "What changed"));
            renderClaims(res.changes, citationMap(res.citations), box);
            box.appendChild(head);
        } else if (docs.length) {
            box.hidden = false;
            box.appendChild(el("h5", "mt-2", "What changed"));
            box.appendChild(el("div", "text-muted", "No new documents since the last read."));
            box.appendChild(head);
        }
    }
    function renderHandoffs(handoffs) {
        var body = document.querySelector("#cpa-handoffs tbody"); body.innerHTML = "";
        (handoffs || []).forEach(function (h) {
            var tr = el("tr");
            tr.appendChild(el("td", "", h.from + " → " + h.to)); tr.appendChild(el("td", "", h.reason));
            tr.appendChild(el("td", "", (h.duration_ms !== undefined ? h.duration_ms + " ms" : ""))); body.appendChild(tr);
        });
    }
    function supervise() {
        setState("Checking for new documents…", "");
        api("supervise", { pid: PID }).then(function (res) {
            if (res.http_status !== 200 || !res.brief) {
                document.getElementById("cpa-brief-reason").textContent = res.reason ? "Supervisor unavailable: " + res.reason + ". Showing the prefetched brief." : "";
                waitForBrief(); return;
            }
            renderChanges(res);
            renderBrief(res.brief);
            renderHandoffs(res.handoffs);
        }).catch(function () { waitForBrief(); });
    }
    function open() {
        api("open_patient", { pid: PID }).then(function (res) {
            if (res.http_status !== 200) {
                setState(stateLabel(res.state || "unable_to_answer"), res.state || "unable_to_answer");
                document.getElementById("cpa-brief-reason").textContent = res.reason || ""; return;
            }
            var p = res.patient;
            document.getElementById("cpa-patient-name").textContent = p.name;
            document.getElementById("cpa-patient-ids").textContent = " · " + (p.sex || "") + ", " + (p.age !== null ? p.age + " y" : "") + ", DOB " + (p.dob || "?")
                + " · pid " + p.pid + (p.time ? " · " + p.time + " " + p.title : "") + " · chart read in " + res.chart_read_ms + " ms";
            supervise();
        });
    }

    // ---- feedback and follow-up (same controls as the rounding-list tab) -----
    function feedbackControls(res) {
        var box = el("div", "cpa-fb mt-1");
        function send(score, category, label) {
            api("feedback", { run_id: res.langsmith_run_id || "", score: score, category: category })
                .then(function () { box.textContent = "Thanks — recorded (" + label + ")."; });
        }
        var up = el("button", "cpa-fb-btn", "Helpful"); up.type = "button";
        up.addEventListener("click", function () { send(1, "good", "helpful"); });
        var down = el("button", "cpa-fb-btn", "Not right"); down.type = "button";
        down.addEventListener("click", function () {
            box.textContent = "";
            box.appendChild(el("span", "", "What was wrong?"));
            [["mismatch", "Doesn't match the record"],
             ["relevance", "Not what I asked"],
             ["completeness", "Missed something"]].forEach(function (opt) {
                var b = el("button", "cpa-fb-btn", opt[1]); b.type = "button";
                b.addEventListener("click", function () { send(0, opt[0], opt[1]); });
                box.appendChild(b);
            });
        });
        box.appendChild(up); box.appendChild(down);
        return box;
    }
    function renderAnswer(res, chat) {
        var turn = el("div", "cpa-turn cpa-turn-a");
        var head = el("div", ""); var st = el("span", "cpa-state", stateLabel(res.state)); st.setAttribute("data-state", res.state); head.appendChild(st);
        turn.appendChild(head);
        var cites = citationMap(res.citations);
        if (res.boundary) { turn.appendChild(el("div", "", res.boundary)); }
        renderClaims(res.claims || [], cites, turn);
        if (res.missing) { turn.appendChild(el("div", "text-muted", res.missing)); }
        // Rule 12: guideline evidence sits apart from patient facts, in its own labelled block.
        if (res.evidence && res.evidence.length) {
            var ev = el("div", "cpa-evidence-block");
            ev.appendChild(el("div", "cpa-evidence-title", "Guideline evidence (general guidance, not a statement about this patient)"));
            renderClaims(res.evidence, cites, ev);
            turn.appendChild(ev);
        }
        if (!res.claims || !res.claims.length) { if (!res.boundary && !res.missing) { turn.appendChild(el("div", "text-muted", res.state_reason || res.reason || "")); } }
        head.appendChild(traceChip(res));
        var det = el("details", "mt-1");
        det.appendChild(el("summary", "cpa-meta", "How this was answered"));
        det.appendChild(el("div", "cpa-meta", (res.state_reason ? res.state_reason + " · " : "") + (res.iterations !== undefined ? res.iterations + " iteration(s)" : "")
            + (res.tool_calls && res.tool_calls.length ? " · tools: " + res.tool_calls.join(" → ") : "") + (res.duration_ms !== undefined ? " · " + res.duration_ms + " ms" : "")
            + " · correlation " + (res.correlation_id || "")
            + (res.langsmith_run_id ? " · langsmith run " + res.langsmith_run_id : "")
            + ((res.removed_claims || []).length ? " · " + res.removed_claims.length + " unverified statement(s) removed" : "")));
        turn.appendChild(det);
        if (res.langsmith_run_id) { turn.appendChild(feedbackControls(res)); }
        chat.appendChild(turn); chat.scrollTop = chat.scrollHeight;
    }
    document.getElementById("cpa-ask-form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var input = document.getElementById("cpa-question"); var q = input.value.trim(); if (!q || !state.ready) { return; }
        var chat = document.getElementById("cpa-chat");
        chat.appendChild(el("div", "cpa-turn cpa-turn-q", q)); input.value = "";
        var btn = document.getElementById("cpa-ask-btn"); btn.disabled = true; btn.textContent = "Working…";
        api("ask", { pid: PID, question: q }).then(function (res) {
            renderAnswer(res, chat);
        }).catch(function () { renderAnswer({ state: "unable_to_answer", state_reason: "request failed; retry or review the chart directly" }, chat); })
          .then(function () { btn.disabled = false; btn.textContent = "Ask"; });
    });

    window.addEventListener("beforeunload", function () { navigator.sendBeacon && api("close", {}); });
    open();
})();
</script>
<?php endif; ?>
</body>
</html>
