<?php

/**
 * Co-Pilot service health: a rolled-up view of the agent's own counters, for the people who own
 * the service rather than the people who debug it.
 *
 * Administrators only, which is the inverse of the co-pilot tab itself (an administrator is denied
 * there by design, and that denial is audited). The page renders server-side from a single signed
 * GET to the agent's /metrics endpoint; the browser never reaches the agent (PRD PHI4).
 *
 * Counters live in the agent's process memory, so every figure is "since the service last started".
 * No identifiers are exposed: /metrics carries counts and timings only, never clinical content.
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
use OpenEMR\Common\Logging\EventAuditLogger;
use OpenEMR\Common\Twig\TwigContainer;
use OpenEMR\Core\Header;
use OpenEMR\Modules\CopilotAgent\AgentClient;
use OpenEMR\Modules\CopilotAgent\AgentUnavailableException;
use OpenEMR\Modules\CopilotAgent\Config;

$username = (string) ($_SESSION['authUser'] ?? '');
$authGroup = (string) ($_SESSION['authProvider'] ?? '');

// The menu entry already carries acl_req, but a URL can be typed. Deny here too, and record it:
// an unauthorised attempt on an operational console is worth seeing in the audit log.
if (!AclMain::aclCheckCore('admin', 'super')) {
    try {
        EventAuditLogger::getInstance()->newEvent(
            'copilot-health-denied',
            $username,
            $authGroup,
            0,
            'administrator role required for the co-pilot health view'
        );
    } catch (\Throwable $e) {
        // fall through to the denial: failing to log must not turn a denial into a page
    }
    echo (new TwigContainer(null, $GLOBALS['kernel']))->getTwig()->render(
        'core/unauthorized.html.twig',
        ['pageTitle' => xl("Co-Pilot Service Health")]
    );
    exit;
}

$correlationId = bin2hex(random_bytes(8));
$config = Config::load((string) ($GLOBALS['OE_SITE_DIR'] ?? ''));

$metrics = null;
$error = null;
if (!$config->isConfigured()) {
    $error = xl("The agent service is not configured for this site.");
} else {
    try {
        $result = (new AgentClient($config))->get('/metrics', $correlationId);
        if ($result['status'] === 200 && is_array($result['json'])) {
            $metrics = $result['json'];
        } else {
            $error = sprintf(xl("The agent service answered with status %s."), (string) $result['status']);
        }
    } catch (AgentUnavailableException $e) {
        $error = xl("The agent service could not be reached.");
    }
}

/** @var array<string, int> $counters */
$counters = [];
foreach ((array) ($metrics['counters'] ?? []) as $name => $value) {
    $counters[(string) $name] = (int) $value;
}
$latency = (array) ($metrics['latency_ms'] ?? []);
$sessionsActive = (int) ($metrics['sessions_active'] ?? 0);

/** Sum every counter whose name starts with the given prefix. */
$sumPrefix = static function (string $prefix) use ($counters): int {
    $total = 0;
    foreach ($counters as $name => $value) {
        if (str_starts_with($name, $prefix)) {
            $total += $value;
        }
    }
    return $total;
};

$briefs = $sumPrefix('brief_state_');
$answers = $sumPrefix('answer_state_');
$sessions = $counters['sessions_opened'] ?? 0;

// "Has the agent done anything since it started?" A session opened without a brief still counts:
// it means a clinician arrived, which is activity worth showing.
$hasActivity = ($sessions + $briefs + $answers) > 0;

$kept = $counters['claims_kept'] ?? 0;
$removed = $counters['claims_removed'] ?? 0;
$verifiedRate = ($kept + $removed) > 0 ? ($kept / ($kept + $removed)) : null;

$feedback = [
    'good' => ['label' => xl("Helpful"), 'count' => $counters['feedback_good'] ?? 0],
    'mismatch' => ['label' => xl("Doesn't match the record"), 'count' => $counters['feedback_mismatch'] ?? 0],
    'relevance' => ['label' => xl("Not what I asked"), 'count' => $counters['feedback_relevance'] ?? 0],
    'completeness' => ['label' => xl("Missed something"), 'count' => $counters['feedback_completeness'] ?? 0],
];

$stateMeta = [
    'complete' => ['label' => xl("Complete"), 'cls' => 'ok', 'note' => xl("everything retrieved, every claim verified")],
    'partial' => ['label' => xl("Partial"), 'cls' => 'warn', 'note' => xl("a source failed or claims were removed, and it said so")],
    'unable_to_answer' => ['label' => xl("Unable to answer"), 'cls' => 'bad', 'note' => xl("the machinery failed, or nothing survived verification")],
    'access_denied' => ['label' => xl("Access denied"), 'cls' => 'neutral', 'note' => xl("the boundary holding; not a failure")],
];

/** @return array<string, int> state => count, for the given prefix */
$statesFor = static function (string $prefix) use ($counters, $stateMeta): array {
    $out = [];
    foreach (array_keys($stateMeta) as $state) {
        $n = $counters[$prefix . $state] ?? 0;
        if ($n > 0) {
            $out[$state] = $n;
        }
    }
    return $out;
};

$ms = static fn(?float $v): string => $v === null ? '—' : ($v >= 1000 ? number_format($v / 1000, 1) . ' s' : ((int) $v) . ' ms');
?>
<!DOCTYPE html>
<html>
<head>
    <?php Header::setupHeader(); ?>
    <title><?php echo xlt("Co-Pilot Service Health"); ?></title>
    <style>
        .cph-wrap { max-width: 72rem; }
        .cph-since { font-size: .85rem; }
        .cph-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1px; background: #dee2e6; border: 1px solid #dee2e6; }
        .cph-tile { background: #fff; padding: .8rem .9rem; }
        .cph-tile .k { font-size: .7rem; letter-spacing: .06em; text-transform: uppercase; color: #6c757d; display: block; }
        .cph-tile .v { font-size: 1.7rem; font-weight: 600; line-height: 1.15; }
        .cph-tile .d { font-size: .78rem; color: #6c757d; display: block; }
        .cph-tile .v.ok { color: #0f7a1a; }
        .cph-bar { display: flex; gap: 2px; height: 26px; margin: .25rem 0 .4rem; }
        .cph-seg { border-radius: 3px; color: #fff; font-size: .75rem; font-weight: 600; display: flex; align-items: center; justify-content: center; min-width: 26px; }
        .cph-seg.ok { background: #0f7a1a; }
        .cph-seg.warn { background: #b9820b; }
        .cph-seg.bad { background: #b02a2a; }
        .cph-seg.neutral { background: #2a6fb5; }
        .cph-key { font-size: .8rem; color: #6c757d; }
        .cph-key i { display: inline-block; width: 11px; height: 11px; border-radius: 2px; margin-right: .3rem; vertical-align: baseline; }
        .cph-key i.ok { background: #0f7a1a; } .cph-key i.warn { background: #b9820b; }
        .cph-key i.bad { background: #b02a2a; } .cph-key i.neutral { background: #2a6fb5; }
        .cph-num { font-variant-numeric: tabular-nums; text-align: right; }
        .cph-note { font-size: .84rem; color: #6c757d; max-width: 70ch; }
    </style>
</head>
<body class="body_top container-fluid">
<div class="cph-wrap">

    <div class="d-flex flex-wrap align-items-center justify-content-between mt-2">
        <h2 class="mb-0"><?php echo xlt("Co-Pilot Service Health"); ?></h2>
        <div class="cph-since text-muted">
            <?php echo xlt("Counters are held in the agent's memory, so every figure is since the service last started."); ?>
        </div>
    </div>

<?php if ($error !== null) : ?>
    <div class="alert alert-warning mt-3" role="alert">
        <strong><?php echo xlt("No metrics available."); ?></strong>
        <?php echo text($error); ?>
        <?php echo xlt("The co-pilot itself may still be working; this view only reads the agent's counters."); ?>
    </div>

<?php elseif (!$hasActivity) : ?>
    <div class="alert alert-info mt-3" role="status">
        <strong><?php echo xlt("No agent calls yet to report since the restart of the stack."); ?></strong>
        <div class="mt-1">
            <?php echo xlt("The agent service is reachable and healthy. Counters start at zero when it restarts, so this view fills in as soon as a clinician opens the co-pilot."); ?>
        </div>
    </div>

<?php else : ?>

    <h5 class="mt-4"><?php echo xlt("What did it do?"); ?></h5>
    <div class="cph-tiles">
        <div class="cph-tile"><span class="k"><?php echo xlt("Sessions opened"); ?></span>
            <span class="v"><?php echo text((string) $sessions); ?></span>
            <span class="d"><?php echo text(sprintf(xl("%s active now"), (string) $sessionsActive)); ?></span></div>
        <div class="cph-tile"><span class="k"><?php echo xlt("Briefs delivered"); ?></span>
            <span class="v"><?php echo text((string) $briefs); ?></span>
            <span class="d"><?php echo xlt("one per patient selected"); ?></span></div>
        <div class="cph-tile"><span class="k"><?php echo xlt("Questions answered"); ?></span>
            <span class="v"><?php echo text((string) $answers); ?></span>
            <span class="d"><?php echo text(sprintf(xl("%s chart lookups"), (string) ($counters['tool_calls'] ?? 0))); ?></span></div>
        <div class="cph-tile"><span class="k"><?php echo xlt("Verified claim rate"); ?></span>
            <span class="v <?php echo $verifiedRate !== null && $verifiedRate >= 0.98 ? 'ok' : ''; ?>">
                <?php echo $verifiedRate === null ? '—' : text(number_format($verifiedRate * 100, 1) . '%'); ?></span>
            <span class="d"><?php echo text(sprintf(xl("%s kept, %s removed"), (string) $kept, (string) $removed)); ?></span></div>
    </div>
    <p class="cph-note mt-2">
        <?php echo xlt("A removed claim is a sentence the verifier deleted before anyone saw it, because it cited nothing, cited another patient's record, cited a record no tool returned in that turn, crossed the advice boundary, or carried a number the cited record does not contain."); ?>
    </p>

    <h5 class="mt-4"><?php echo xlt("How did the answers end?"); ?></h5>
    <?php foreach ([['brief_state_', xl("Rounding briefs"), $briefs], ['answer_state_', xl("Follow-up answers"), $answers]] as [$prefix, $title, $total]) : ?>
        <?php $states = $statesFor($prefix); ?>
        <?php if ($total > 0) : ?>
            <div class="d-flex justify-content-between mt-2" style="font-size:.88rem">
                <span><?php echo text($title); ?></span><span><?php echo text((string) $total); ?></span>
            </div>
            <div class="cph-bar">
                <?php foreach ($states as $state => $n) : ?>
                    <div class="cph-seg <?php echo attr($stateMeta[$state]['cls']); ?>"
                         style="flex:<?php echo attr((string) $n); ?>"
                         title="<?php echo attr($stateMeta[$state]['label'] . ' — ' . $n . ' of ' . $total); ?>">
                        <?php echo text((string) $n); ?>
                    </div>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>
    <?php endforeach; ?>
    <div class="cph-key mt-1">
        <?php foreach ($stateMeta as $meta) : ?>
            <span class="mr-3"><i class="<?php echo attr($meta['cls']); ?>"></i><?php echo text($meta['label']); ?>
                &mdash; <?php echo text($meta['note']); ?></span>
        <?php endforeach; ?>
    </div>
    <p class="cph-note mt-2">
        <?php echo xlt("Access denied is not an error: it is the patient boundary holding, and it is audited. The state to investigate is unable to answer."); ?>
    </p>

    <h5 class="mt-4"><?php echo xlt("Was it fast enough?"); ?></h5>
    <table class="table table-sm" style="max-width:46rem">
        <thead><tr>
            <th><?php echo xlt("Path"); ?></th>
            <th class="cph-num"><?php echo xlt("p50"); ?></th>
            <th class="cph-num"><?php echo xlt("p95"); ?></th>
            <th class="cph-num"><?php echo xlt("p99"); ?></th>
            <th class="cph-num"><?php echo xlt("Samples"); ?></th>
        </tr></thead>
        <tbody>
        <?php foreach ([['brief_ms', xl("Rounding brief")], ['answer_ms', xl("Follow-up answer")]] as [$key, $label]) : ?>
            <?php $row = (array) ($latency[$key] ?? []); ?>
            <tr>
                <td><?php echo text($label); ?></td>
                <td class="cph-num"><?php echo text($ms(isset($row['p50']) ? (float) $row['p50'] : null)); ?></td>
                <td class="cph-num"><?php echo text($ms(isset($row['p95']) ? (float) $row['p95'] : null)); ?></td>
                <td class="cph-num"><?php echo text($ms(isset($row['p99']) ? (float) $row['p99'] : null)); ?></td>
                <td class="cph-num"><?php echo text((string) ((int) ($row['n'] ?? 0))); ?></td>
            </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <?php $answerN = (int) (($latency['answer_ms']['n'] ?? 0)); ?>
    <?php if ($answerN > 0 && $answerN < 20) : ?>
        <p class="cph-note">
            <?php echo text(sprintf(xl("Percentiles are computed over %s samples. Below roughly twenty they describe shape, not performance."), (string) $answerN)); ?>
        </p>
    <?php endif; ?>

    <h5 class="mt-4"><?php echo xlt("What did clinicians say?"); ?></h5>
    <?php $ratings = array_sum(array_column($feedback, 'count')); ?>
    <?php if ($ratings === 0) : ?>
        <p class="cph-note"><?php echo xlt("No ratings submitted since the service started."); ?></p>
    <?php else : ?>
        <table class="table table-sm" style="max-width:40rem">
            <thead><tr><th><?php echo xlt("Rating"); ?></th><th class="cph-num"><?php echo xlt("Count"); ?></th></tr></thead>
            <tbody>
            <?php foreach ($feedback as $row) : ?>
                <tr><td><?php echo text($row['label']); ?></td>
                    <td class="cph-num"><?php echo text((string) $row['count']); ?></td></tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    <?php endif; ?>

    <h5 class="mt-4"><?php echo xlt("Boundary and failure counters"); ?></h5>
    <div class="cph-tiles">
        <div class="cph-tile"><span class="k"><?php echo xlt("Auth rejections"); ?></span>
            <span class="v <?php echo ($counters['auth_rejected'] ?? 0) === 0 ? 'ok' : ''; ?>">
                <?php echo text((string) ($counters['auth_rejected'] ?? 0)); ?></span>
            <span class="d"><?php echo xlt("unsigned or stale requests"); ?></span></div>
        <div class="cph-tile"><span class="k"><?php echo xlt("Patient scope denials"); ?></span>
            <span class="v"><?php echo text((string) ($counters['answer_state_access_denied'] ?? 0)); ?></span>
            <span class="d"><?php echo xlt("refused, and audited"); ?></span></div>
        <div class="cph-tile"><span class="k"><?php echo xlt("Provider refusals"); ?></span>
            <span class="v <?php echo ($counters['open_refused_provider'] ?? 0) === 0 ? 'ok' : ''; ?>">
                <?php echo text((string) ($counters['open_refused_provider'] ?? 0)); ?></span>
            <span class="d"><?php echo xlt("model not on the allowlist"); ?></span></div>
        <div class="cph-tile"><span class="k"><?php echo xlt("Unable to answer"); ?></span>
            <span class="v <?php echo ($counters['answer_state_unable_to_answer'] ?? 0) === 0 ? 'ok' : ''; ?>">
                <?php echo text((string) ($counters['answer_state_unable_to_answer'] ?? 0)); ?></span>
            <span class="d"><?php echo xlt("investigate these"); ?></span></div>
    </div>

<?php endif; ?>

    <p class="cph-note mt-4">
        <?php echo xlt("Read from the agent's /metrics endpoint over the private network, signed with the shared secret. It carries counts and timings only: no patient, user or question content passes through this page."); ?>
        <?php echo text(sprintf(xl("Correlation id %s."), $correlationId)); ?>
    </p>

</div>
</body>
</html>
