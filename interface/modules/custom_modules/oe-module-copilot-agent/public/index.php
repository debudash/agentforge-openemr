<?php

/**
 * Clinical Co-Pilot tab: rounding list on the left, patient brief and follow-up
 * conversation on the right. All data comes from api.php; this page only renders.
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

// Per-session token for the JSON endpoint, derived like CsrfUtils does: globals.php closes the
// session for writing early, so a value stored here would not persist. Session access is
// confined to this entry point.
$csrf = hash_hmac('sha256', 'copilot', (string) ($_SESSION['csrf_private_key'] ?? session_id()));

$scope = PanelScope::forCurrentUser();
[$isHospitalist, $roleReason] = $scope->isHospitalist();
$config = Config::load((string) ($GLOBALS['OE_SITE_DIR'] ?? ''));
?>
<!DOCTYPE html>
<html>
<head>
    <?php Header::setupHeader(); ?>
    <title><?php echo xlt("Clinical Co-Pilot"); ?></title>
    <style>
        .cpa-layout { display: flex; gap: 1rem; min-height: calc(100vh - 140px); }
        .cpa-list { flex: 0 0 300px; }
        .cpa-main { flex: 1 1 auto; min-width: 0; }
        .cpa-patient { cursor: pointer; }
        .cpa-patient:focus { outline: 3px solid #0d6efd; outline-offset: -3px; }
        .cpa-dot { display: inline-block; width: .7rem; height: .7rem; border-radius: 50%; margin-right: .4rem; vertical-align: middle; border: 1px solid #666; }
        .cpa-dot[data-status="queued"] { background: #ddd; }
        .cpa-dot[data-status="generating"] { background: #ffd54f; }
        .cpa-dot[data-status="ready"] { background: #66bb6a; }
        .cpa-dot[data-status="failed"] { background: #e57373; }
        .cpa-state { font-weight: 600; }
        .cpa-state[data-state="complete"] { color: #1b5e20; }
        .cpa-state[data-state="partial"] { color: #8a6d00; }
        .cpa-state[data-state="unable_to_answer"] { color: #b71c1c; }
        .cpa-state[data-state="access_denied"] { color: #b71c1c; }
        .cpa-cite { font-size: .8rem; margin-left: .3rem; }
        .cpa-claim { margin-bottom: .35rem; }
        .cpa-evidence { background: #f7f7f7; border-left: 3px solid #999; padding: .4rem .6rem; font-size: .85rem; margin: .3rem 0 .6rem; }
        .cpa-chat { max-height: 45vh; overflow-y: auto; }
        .cpa-turn-q { background: #eef3ff; }
        .cpa-turn-a { background: #f3fff3; }
        .cpa-turn { padding: .5rem .75rem; border-radius: .4rem; margin-bottom: .5rem; }
        .cpa-meta { font-size: .78rem; color: #555; }
        .cpa-rule-flag { color: #8a6d00; font-weight: 600; }
        .cpa-rule-engine_failure, .cpa-rule-unable_to_evaluate { color: #b71c1c; }
        .cpa-disclaimer { font-size: .85rem; }
        .sr-only-focusable:focus { position: static; }
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
        &middot; <strong><?php echo xlt("Assigned patients"); ?>:</strong> <?php echo text((string) $scope->panelSize()); ?>
    </p>

<?php if (!$isHospitalist) : ?>
    <div class="alert alert-danger" role="alert">
        <strong><?php echo xlt("Access denied."); ?></strong>
        <?php echo text($roleReason); ?>.
        <?php echo xlt("The co-pilot is available to providers in the Physicians group only. This denial has been recorded."); ?>
    </div>
<?php elseif (!$config->isConfigured()) : ?>
    <div class="alert alert-danger" role="alert">
        <strong><?php echo xlt("Not configured."); ?></strong>
        <?php echo xlt("Set COPILOT_AGENT_URL and COPILOT_SHARED_SECRET (environment or sites/<site>/copilot-config.php)."); ?>
    </div>
<?php else : ?>
    <div class="cpa-layout">
        <aside class="cpa-list card" aria-label="<?php echo xla("Rounding list"); ?>">
            <div class="card-header py-2">
                <strong id="cpa-list-title"><?php echo xlt("Today's rounding list"); ?></strong>
                <div class="cpa-meta" id="cpa-prefetch" aria-live="polite"></div>
            </div>
            <div class="list-group list-group-flush" id="cpa-patients" role="listbox" aria-labelledby="cpa-list-title"></div>
        </aside>

        <main class="cpa-main">
            <div id="cpa-empty" class="card"><div class="card-body text-muted">
                <?php echo xlt("Select a patient to see the pre-rounding brief: primary diagnosis, co-morbidities, recent labs and demo-reference checks, care-plan adherence signals, active medications and allergies."); ?>
            </div></div>

            <div id="cpa-patient" class="card" hidden>
                <div class="card-header py-2">
                    <div class="d-flex flex-wrap justify-content-between align-items-center">
                        <div>
                            <strong id="cpa-patient-name"></strong>
                            <span class="cpa-meta" id="cpa-patient-ids"></span>
                        </div>
                        <div>
                            <span class="cpa-state" id="cpa-brief-state" data-state=""></span>
                        </div>
                    </div>
                    <div class="cpa-meta" id="cpa-brief-window"></div>
                    <div class="cpa-meta" id="cpa-brief-reason"></div>
                </div>
                <div class="card-body" id="cpa-brief"></div>
                <div class="card-body border-top">
                    <details>
                        <summary><?php echo xlt("Constraint checks and data sources"); ?></summary>
                        <table class="table table-sm mt-2" id="cpa-rules"><caption class="sr-only"><?php echo xlt("Rule engine outcomes"); ?></caption>
                            <thead><tr><th><?php echo xlt("Rule"); ?></th><th><?php echo xlt("Outcome"); ?></th><th><?php echo xlt("Detail"); ?></th></tr></thead><tbody></tbody></table>
                        <div class="cpa-meta" id="cpa-sources"></div>
                        <div class="cpa-meta" id="cpa-removed"></div>
                    </details>
                </div>
                <div class="card-body border-top">
                    <h5><?php echo xlt("Follow-up questions"); ?></h5>
                    <div class="cpa-chat" id="cpa-chat" aria-live="polite"></div>
                    <form id="cpa-ask-form" class="form-inline mt-2">
                        <label for="cpa-question" class="sr-only"><?php echo xlt("Question about this patient"); ?></label>
                        <input type="text" class="form-control mr-2 flex-grow-1" id="cpa-question" maxlength="2000" autocomplete="off"
                               placeholder="<?php echo xla("e.g. What was the last potassium? Any medication past its end date?"); ?>">
                        <button type="submit" class="btn btn-primary" id="cpa-ask-btn"><?php echo xlt("Ask"); ?></button>
                    </form>
                </div>
            </div>
        </main>
    </div>
<?php endif; ?>

<script>
(function () {
    "use strict";
    var API = "api.php";
    var CSRF = <?php echo json_encode($csrf); ?>;
    var state = { patients: {}, order: [], activePid: null, polling: null, budget: 90, opened: 0 };

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) { node.className = cls; }
        if (text !== undefined && text !== null) { node.textContent = String(text); }
        return node;
    }
    function api(action, body) {
        var options = { credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Copilot-Csrf": CSRF } };
        if (body) { options.method = "POST"; options.body = JSON.stringify(body); }
        return fetch(API + "?action=" + encodeURIComponent(action), options).then(function (r) {
            return r.json().then(function (j) { j.http_status = r.status; return j; });
        });
    }
    function stateLabel(s) {
        return { complete: "Complete for requested scope", partial: "Partial", unable_to_answer: "Unable to answer", access_denied: "Access denied" }[s] || s;
    }

    // ---- rounding list -----------------------------------------------------
    function renderList() {
        var list = document.getElementById("cpa-patients");
        list.innerHTML = "";
        if (!state.order.length) {
            list.appendChild(el("div", "list-group-item text-muted", "No appointments booked for you today."));
            return;
        }
        state.order.forEach(function (pid) {
            var p = state.patients[pid];
            var item = el("button", "list-group-item list-group-item-action cpa-patient" + (pid === state.activePid ? " active" : ""));
            item.type = "button"; item.setAttribute("role", "option"); item.setAttribute("aria-selected", pid === state.activePid ? "true" : "false");
            var briefUnusable = p.status === "ready" && (p.brief_state === "unable_to_answer" || p.brief_state === "access_denied");
            var dotStatus = briefUnusable ? "failed" : (p.status || "queued");
            var dot = el("span", "cpa-dot"); dot.setAttribute("data-status", dotStatus); dot.title = dotStatus;
            item.appendChild(dot);
            item.appendChild(el("strong", "", p.time + "  " + p.name));
            var meta = el("div", "cpa-meta", (p.sex || "") + (p.age !== null ? ", " + p.age + " y" : "") + (p.dob ? ", DOB " + p.dob : "")
                + " · " + (briefUnusable ? "brief " + stateLabel(p.brief_state).toLowerCase()
                : p.status === "ready" ? "brief " + (p.brief_state === "partial" ? "partial" : "ready") + (p.ready_in_ms ? " in " + (p.ready_in_ms / 1000).toFixed(1) + " s" : "")
                : p.status === "failed" ? "brief failed" : p.status || "queued"));
            item.appendChild(meta);
            item.addEventListener("click", function () { selectPatient(pid); });
            list.appendChild(item);
        });
    }
    function open() {
        document.getElementById("cpa-prefetch").textContent = "Reading charts…";
        api("open").then(function (res) {
            if (res.http_status !== 200) {
                document.getElementById("cpa-prefetch").textContent = stateLabel(res.state) + ": " + (res.reason || "");
                return;
            }
            state.budget = res.prefetch_budget_s || 90; state.opened = Date.now();
            document.getElementById("cpa-list-title").textContent = "Rounding list for " + res.date;
            res.patients.forEach(function (p) { p.status = "queued"; state.patients[p.pid] = p; state.order.push(p.pid); });
            renderList();
            document.getElementById("cpa-prefetch").textContent = res.patients.length + " patient(s); charts read in " + res.chart_read_ms + " ms. Prefetching briefs…";
            if (res.patients.length) { poll(); }
        });
    }
    function poll() {
        api("status").then(function (res) {
            var allDone = true;
            (res.patients || []).forEach(function (s) {
                var p = state.patients[s.pid]; if (!p) { return; }
                p.status = s.status; p.ready_in_ms = s.ready_in_ms; p.brief_state = s.state;
                if (s.status === "queued" || s.status === "generating") { allDone = false; }
            });
            renderList();
            var elapsed = ((Date.now() - state.opened) / 1000).toFixed(0);
            var ready = state.order.filter(function (pid) { return state.patients[pid].status === "ready"; }).length;
            document.getElementById("cpa-prefetch").textContent = ready + "/" + state.order.length + " briefs ready · " + elapsed + " s of " + state.budget + " s budget";
            if (!allDone) { state.polling = setTimeout(poll, 2000); }
        });
    }

    // ---- brief -------------------------------------------------------------
    function citeChips(sourceIds, citations, container) {
        sourceIds.forEach(function (sid) {
            var c = citations[sid];
            var chip = el("button", "badge badge-light border cpa-cite", c ? (c.type + " · " + (c.date || "")) : sid);
            chip.type = "button"; chip.title = c ? c.label : sid; chip.setAttribute("aria-label", "Show evidence " + sid);
            chip.addEventListener("click", function () {
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
    function renderClaims(claims, citations, container) {
        claims.forEach(function (claim) {
            var row = el("div", "cpa-claim"); row.appendChild(el("span", "", claim.text)); citeChips(claim.source_ids, citations, row); container.appendChild(row);
        });
    }
    function citationMap(list) { var m = {}; (list || []).forEach(function (c) { m[c.source_id] = c; }); return m; }
    function renderBrief(brief) {
        var box = document.getElementById("cpa-brief"); box.innerHTML = "";
        var st = document.getElementById("cpa-brief-state"); st.textContent = stateLabel(brief.state); st.setAttribute("data-state", brief.state);
        document.getElementById("cpa-brief-window").textContent = "Comparison window: " + brief.comparison_window + " · chart read " + brief.generated_at + " · brief " + brief.duration_ms + " ms · correlation " + brief.correlation_id;
        document.getElementById("cpa-brief-reason").textContent = brief.state_reason || "";
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
    }
    function selectPatient(pid) {
        state.activePid = pid; renderList();
        var p = state.patients[pid];
        document.getElementById("cpa-empty").hidden = true;
        var card = document.getElementById("cpa-patient"); card.hidden = false;
        document.getElementById("cpa-patient-name").textContent = p.name;
        document.getElementById("cpa-patient-ids").textContent = " · " + (p.sex || "") + ", " + (p.age !== null ? p.age + " y" : "") + ", DOB " + (p.dob || "?") + " · pid " + pid + " · " + p.time + " " + p.title;
        document.getElementById("cpa-chat").innerHTML = "";     // FR5: conversation never crosses patients
        document.getElementById("cpa-brief").innerHTML = "";
        document.getElementById("cpa-brief-state").textContent = "Loading…";
        document.getElementById("cpa-brief-reason").textContent = "";
        api("select", { pid: pid }).then(function (res) {
            if (res.http_status !== 200 || res.status === "denied") {
                document.getElementById("cpa-brief-state").textContent = stateLabel(res.state || "access_denied");
                document.getElementById("cpa-brief-reason").textContent = res.reason || (res.brief && res.brief.state_reason) || ""; return;
            }
            if (res.status === "ready" && res.brief) { renderBrief(res.brief); return; }
            if (res.status === "failed") {
                document.getElementById("cpa-brief-state").textContent = stateLabel("unable_to_answer");
                document.getElementById("cpa-brief-reason").textContent = res.error || "brief generation failed"; return;
            }
            document.getElementById("cpa-brief-state").textContent = "Brief is being prepared…";
            setTimeout(function () { if (state.activePid === pid) { selectPatient(pid); } }, 2000);
        });
    }

    // ---- follow-up ---------------------------------------------------------
    function renderAnswer(res, chat) {
        var turn = el("div", "cpa-turn cpa-turn-a");
        var head = el("div", ""); var st = el("span", "cpa-state", stateLabel(res.state)); st.setAttribute("data-state", res.state); head.appendChild(st);
        turn.appendChild(head);
        var cites = citationMap(res.citations);
        if (res.boundary) { turn.appendChild(el("div", "", res.boundary)); }
        renderClaims(res.claims || [], cites, turn);
        if (res.missing) { turn.appendChild(el("div", "text-muted", res.missing)); }
        if (!res.claims || !res.claims.length) { if (!res.boundary && !res.missing) { turn.appendChild(el("div", "text-muted", res.state_reason || res.reason || "")); } }
        var meta = el("div", "cpa-meta", (res.state_reason ? res.state_reason + " · " : "") + (res.iterations !== undefined ? res.iterations + " iteration(s)" : "")
            + (res.tool_calls && res.tool_calls.length ? " · tools: " + res.tool_calls.join(" → ") : "") + (res.duration_ms !== undefined ? " · " + res.duration_ms + " ms" : "")
            + " · correlation " + (res.correlation_id || "")
            + ((res.removed_claims || []).length ? " · " + res.removed_claims.length + " unverified statement(s) removed" : ""));
        turn.appendChild(meta);
        if (res.langsmith_run_id !== undefined) {
            var fb = el("div", "mt-1");
            [["good", 1, "Helpful"], ["citation", 0, "Citation issue"], ["relevance", 0, "Not relevant"], ["completeness", 0, "Incomplete"]].forEach(function (opt) {
                var b = el("button", "btn btn-sm btn-outline-secondary mr-1", opt[2]); b.type = "button";
                b.addEventListener("click", function () {
                    api("feedback", { run_id: res.langsmith_run_id || "", score: opt[1], category: opt[0] }).then(function () { fb.textContent = "Thanks, feedback recorded (" + opt[2] + ")."; });
                });
                fb.appendChild(b);
            });
            turn.appendChild(fb);
        }
        chat.appendChild(turn); chat.scrollTop = chat.scrollHeight;
    }
    document.getElementById("cpa-ask-form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var input = document.getElementById("cpa-question"); var q = input.value.trim(); if (!q || state.activePid === null) { return; }
        var chat = document.getElementById("cpa-chat"); var pid = state.activePid;
        chat.appendChild(el("div", "cpa-turn cpa-turn-q", q)); input.value = "";
        var btn = document.getElementById("cpa-ask-btn"); btn.disabled = true; btn.textContent = "Working…";
        api("ask", { pid: pid, question: q }).then(function (res) {
            if (state.activePid !== pid) { return; }   // patient changed while in flight: discard
            renderAnswer(res, chat);
        }).catch(function () { renderAnswer({ state: "unable_to_answer", state_reason: "request failed; retry or review the chart directly" }, chat); })
          .then(function () { btn.disabled = false; btn.textContent = "Ask"; });
    });

    window.addEventListener("beforeunload", function () { navigator.sendBeacon && api("close", {}); });
    open();
})();
</script>
</body>
</html>
