<?php

/**
 * JSON endpoint behind the CopilotAgent tab. The browser calls this (same origin,
 * OpenEMR session cookie); this proxies to the agent service over the private network
 * with a signed request. The browser never talks to the agent or the model (PHI4).
 *
 * Actions: open, status, select, ask, feedback, close.
 * Every request: signed-in user, hospitalist role, CSRF token on POST, patient in scope.
 * Every outcome is audited with the correlation ID so a request can be reconstructed
 * across OpenEMR's log, the agent's event stream and the LangSmith trace (FR14, NFR6).
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

use OpenEMR\Common\Logging\EventAuditLogger;
use OpenEMR\Modules\CopilotAgent\AgentClient;
use OpenEMR\Modules\CopilotAgent\AgentUnavailableException;
use OpenEMR\Modules\CopilotAgent\ChartReader;
use OpenEMR\Modules\CopilotAgent\Config;
use OpenEMR\Modules\CopilotAgent\DocumentWriter;
use OpenEMR\Modules\CopilotAgent\PanelScope;
use OpenEMR\Modules\CopilotAgent\ScopeDeniedException;

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

// Superglobals are read only here, at the entry point, and parsed immediately.
$action = is_string($_GET['action'] ?? null) ? $_GET['action'] : '';
// Week 2: the patient-record tab runs its own agent session, so it never replaces the
// rounding-list session a clinician may have open in the other tab. Anything else is the
// Week 1 rounding context, whose session id is unchanged.
$context = (($_GET['context'] ?? '') === 'patient') ? 'patient' : 'rounds';
$method = (string) ($_SERVER['REQUEST_METHOD'] ?? 'GET');
$csrfHeader = (string) ($_SERVER['HTTP_X_COPILOT_CSRF'] ?? '');
// Same derivation as index.php (the session is read-only past globals.php).
$sessionCsrf = hash_hmac('sha256', 'copilot', (string) ($_SESSION['csrf_private_key'] ?? session_id()));
$authGroup = (string) ($_SESSION['authProvider'] ?? '');
$correlationId = sprintf(
    '%s-%s-4%s-%s-%s',
    bin2hex(random_bytes(4)),
    bin2hex(random_bytes(2)),
    substr(bin2hex(random_bytes(2)), 1),
    dechex(0x8 | (random_int(0, 3))) . substr(bin2hex(random_bytes(2)), 1),
    bin2hex(random_bytes(6))
);
$input = [];
if ($method === 'POST') {
    if (!empty($_FILES)) {
        $input = $_POST;    // a multipart upload (attach): the fields beside the file
    } else {
        $raw = file_get_contents('php://input');
        $decoded = is_string($raw) ? json_decode($raw, true) : null;
        $input = is_array($decoded) ? $decoded : [];
    }
}
// The encounter in the session belongs to the session's patient; it is only attached to a write
// for that same patient, never to a request that names a different pid.
$sessionPid = (int) ($_SESSION['pid'] ?? 0);
$sessionEncounter = (int) ($_SESSION['encounter'] ?? 0);

/**
 * @param array<string, mixed> $payload
 */
function respond(int $status, array $payload, string $correlationId): never
{
    http_response_code($status);
    $payload['correlation_id'] = $correlationId;
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function audit(string $event, string $username, string $group, bool $success, string $comment, ?int $pid = null): void
{
    try {
        EventAuditLogger::getInstance()->newEvent($event, $username, $group, $success ? 1 : 0, $comment, $pid);
    } catch (\Throwable $e) {
        // The PRD requires failing closed when the audit event cannot be recorded.
        throw new \RuntimeException('audit event could not be recorded', 0, $e);
    }
}

$username = '';
try {
    $scope = PanelScope::forCurrentUser();
    $username = $scope->username();

    [$isHospitalist, $roleReason] = $scope->isHospitalist();
    if (!$isHospitalist) {
        audit('copilot-role-denied', $username, $authGroup, false, 'cid=' . $correlationId . ' ' . $roleReason);
        respond(403, ['state' => 'access_denied', 'reason' => $roleReason], $correlationId);
    }

    if ($method === 'POST' && ($sessionCsrf === '' || !hash_equals($sessionCsrf, $csrfHeader))) {
        respond(403, ['state' => 'unable_to_answer', 'reason' => 'invalid request token; reload the page'], $correlationId);
    }

    // Patient scope is checked before anything else can answer, so an out-of-panel request is
    // always refused as such, whatever the state of the agent service.
    if (in_array($action, ['select', 'ask', 'open_patient', 'attach', 'persist_extraction'], true)) {
        $scope->assertInScope((int) ($input['pid'] ?? 0));
    }

    $config = Config::load((string) ($GLOBALS['OE_SITE_DIR'] ?? ''));
    if (!$config->isConfigured()) {
        respond(503, ['state' => 'unable_to_answer', 'reason' => 'the co-pilot agent service is not configured for this site'], $correlationId);
    }
    $client = new AgentClient($config);
    $sessionId = hash('sha256', session_id() . '|' . $scope->userId() . ($context === 'patient' ? '|patient' : ''));

    switch ($action) {
        case 'attach':
            // Week 2: store a document in the patient's chart. Extracting it is a separate step, so
            // a stored document with nothing extracted yet is a normal state, not a failure.
            $pid = (int) ($input['pid'] ?? 0);
            $docType = (string) ($input['doc_type'] ?? '');
            if (!in_array($docType, ['lab_pdf', 'intake_form'], true)) {
                respond(400, ['state' => 'unable_to_answer', 'reason' => 'doc_type must be lab_pdf or intake_form'], $correlationId);
            }
            $file = $_FILES['file'] ?? null;
            if (!is_array($file) || (int) ($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK || !is_uploaded_file((string) $file['tmp_name'])) {
                respond(400, ['state' => 'unable_to_answer', 'reason' => 'no file was uploaded'], $correlationId);
            }
            $writer = new DocumentWriter($scope);
            $docId = $writer->storeDocument(
                $pid,
                (string) $file['tmp_name'],
                basename((string) ($file['name'] ?? 'document')),
                (string) mime_content_type((string) $file['tmp_name']),   // sniffed, never the client's claim
                $docType === 'lab_pdf' ? DocumentWriter::CATEGORY_LAB : DocumentWriter::CATEGORY_RECORD,
                $sessionPid === $pid ? $sessionEncounter : 0
            );
            // Document id, type and size: enough to trace it, nothing that describes its content.
            audit('copilot-document-attached', $username, $authGroup, true,
                'cid=' . $correlationId . ' doc=' . $docId . ' type=' . $docType . ' bytes=' . (int) ($file['size'] ?? 0), $pid);
            respond(200, ['doc_id' => $docId, 'doc_type' => $docType, 'processed' => $writer->orderFor($docId) !== null], $correlationId);

        case 'persist_extraction':
            // Week 2: the module writes what the agent extracted. Idempotent per document.
            $pid = (int) ($input['pid'] ?? 0);
            $docId = (int) ($input['doc_id'] ?? 0);
            $docType = (string) ($input['doc_type'] ?? 'lab_pdf');
            $extraction = is_array($input['extraction'] ?? null) ? $input['extraction'] : null;
            if ($docId <= 0 || $extraction === null) {
                respond(400, ['state' => 'unable_to_answer', 'reason' => 'doc_id and extraction are required'], $correlationId);
            }
            if ($docType !== 'lab_pdf') {
                respond(400, ['state' => 'unable_to_answer', 'reason' => 'only lab_pdf extractions are persisted as results'], $correlationId);
            }
            $writer = new DocumentWriter($scope);
            $existing = $writer->orderFor($docId);
            if ($existing !== null) {
                respond(200, ['already_persisted' => true, 'order_id' => $existing, 'source_ids' => $writer->sourceIdsFor($docId),
                              'skipped' => [], 'attributed_to' => null], $correlationId);
            }
            $written = $writer->persistLabDocument($pid, $docId, $extraction, $sessionPid === $pid ? $sessionEncounter : 0,
                (string) ($input['model'] ?? 'unknown'));
            // Counts and ids only: no value extracted from the document reaches the log.
            audit('copilot-extraction-persisted', $username, $authGroup, true,
                'cid=' . $correlationId . ' doc=' . $docId . ' order=' . $written['order_id'] . ' results=' . count($written['source_ids'])
                . ' skipped=' . count($written['skipped']) . ' attributed=' . $written['attributed_to'], $pid);
            respond(200, $written + ['already_persisted' => false], $correlationId);

        case 'open_patient':
            // One patient, reached from its own record. Scope was asserted above. The chart read
            // and the agent call are the same as 'open' with a list of one.
            $pid = (int) ($input['pid'] ?? 0);
            $date = date('Y-m-d');
            $appointment = null;
            foreach ($scope->roundingList($date) as $booked) {
                if ($booked['pid'] === $pid) {
                    $appointment = $booked;
                    break;
                }
            }
            $readStarted = microtime(true);
            $chart = (new ChartReader($scope, $config))->read($pid, $appointment);
            $readMs = (int) round((microtime(true) - $readStarted) * 1000);
            $result = $client->post('/session/open', [
                'session_id' => $sessionId,
                'user' => ['id' => $scope->userId(), 'username' => $username, 'name' => $scope->displayName(), 'groups' => $scope->groups()],
                'charts' => [$chart],
            ], $correlationId);
            if ($result['status'] !== 200 || $result['json'] === null) {
                audit('copilot-open', $username, $authGroup, false, 'cid=' . $correlationId . ' entry=patient agent status=' . $result['status'], $pid);
                respond(503, ['state' => 'unable_to_answer', 'reason' => 'the agent service refused the session (status ' . $result['status'] . ')',
                              'detail' => $result['json']['detail'] ?? null], $correlationId);
            }
            audit('copilot-open', $username, $authGroup, true, 'cid=' . $correlationId . ' entry=patient chart_read_ms=' . $readMs, $pid);
            respond(200, [
                'date' => $date,
                'user' => ['name' => $scope->displayName(), 'username' => $username, 'panel_size' => $scope->panelSize()],
                'patient' => [
                    'pid' => $pid,
                    'name' => preg_replace('/\d+/', '', (string) $chart['patient']['name']),
                    'dob' => $chart['patient']['dob'],
                    'age' => $chart['patient']['age'],
                    'sex' => $chart['patient']['sex'],
                    'time' => $appointment['time'] ?? '',
                    'title' => $appointment['title'] ?? '',
                    'sources' => $chart['sources'],
                ],
                'chart_read_ms' => $readMs,
                'prefetch_budget_s' => $result['json']['prefetch_budget_s'] ?? 90,
                'disclaimer' => $result['json']['disclaimer'] ?? 'Demo data only. Not clinically validated for patient care.',
                'rejected' => $result['json']['rejected'] ?? [],
            ], $correlationId);

        case 'open':
            $date = date('Y-m-d');
            $list = $scope->roundingList($date);
            $reader = new ChartReader($scope, $config);
            $charts = [];
            $patients = [];
            $readStarted = microtime(true);
            foreach ($list as $appointment) {
                $chart = $reader->read($appointment['pid'], $appointment);
                $charts[] = $chart;
                $patients[] = [
                    'pid' => $appointment['pid'],
                    'name' => preg_replace('/\d+/', '', (string) $chart['patient']['name']),
                    'dob' => $chart['patient']['dob'],
                    'age' => $chart['patient']['age'],
                    'sex' => $chart['patient']['sex'],
                    'time' => $appointment['time'],
                    'title' => $appointment['title'],
                    'sources' => $chart['sources'],
                ];
            }
            $readMs = (int) round((microtime(true) - $readStarted) * 1000);
            $result = $client->post('/session/open', [
                'session_id' => $sessionId,
                'user' => ['id' => $scope->userId(), 'username' => $username, 'name' => $scope->displayName(), 'groups' => $scope->groups()],
                'charts' => $charts,
            ], $correlationId);
            if ($result['status'] !== 200 || $result['json'] === null) {
                audit('copilot-open', $username, $authGroup, false, 'cid=' . $correlationId . ' agent status=' . $result['status']);
                respond(503, ['state' => 'unable_to_answer', 'reason' => 'the agent service refused the session (status ' . $result['status'] . ')',
                              'detail' => $result['json']['detail'] ?? null], $correlationId);
            }
            audit('copilot-open', $username, $authGroup, true, 'cid=' . $correlationId . ' date=' . $date . ' patients=' . count($list) . ' chart_read_ms=' . $readMs);
            respond(200, [
                'date' => $date,
                'user' => ['name' => $scope->displayName(), 'username' => $username, 'panel_size' => $scope->panelSize()],
                'patients' => $patients,
                'chart_read_ms' => $readMs,
                'prefetch_budget_s' => $result['json']['prefetch_budget_s'] ?? 90,
                'disclaimer' => $result['json']['disclaimer'] ?? 'Demo data only. Not clinically validated for patient care.',
                'rejected' => $result['json']['rejected'] ?? [],
            ], $correlationId);

        case 'status':
            $result = $client->get('/session/' . $sessionId . '/status', $correlationId);
            respond($result['status'] === 200 ? 200 : 503, $result['json'] ?? ['state' => 'unable_to_answer', 'reason' => 'no session'], $correlationId);

        case 'select':
            $pid = (int) ($input['pid'] ?? 0);
            $scope->assertInScope($pid);
            $result = $client->post('/session/' . $sessionId . '/select', ['pid' => $pid], $correlationId);
            $brief = $result['json']['brief'] ?? null;
            audit('copilot-select', $username, $authGroup, $result['status'] === 200,
                'cid=' . $correlationId . ' status=' . ($result['json']['status'] ?? '?') . ' state=' . ($brief['state'] ?? '-')
                . ' brief_ms=' . ($brief['duration_ms'] ?? '-') . ' removed=' . count($brief['removed_claims'] ?? []), $pid);
            respond($result['status'] === 200 ? 200 : 503, $result['json'] ?? ['state' => 'unable_to_answer', 'reason' => 'agent error'], $correlationId);

        case 'ask':
            $pid = (int) ($input['pid'] ?? 0);
            $question = trim((string) ($input['question'] ?? ''));
            if ($question === '' || mb_strlen($question) > 2000) {
                respond(400, ['state' => 'unable_to_answer', 'reason' => 'question must be 1-2000 characters'], $correlationId);
            }
            $scope->assertInScope($pid);
            $result = $client->post('/session/' . $sessionId . '/ask', ['pid' => $pid, 'question' => $question], $correlationId);
            $answer = $result['json'] ?? [];
            // FR14: decision, tool sequence, verification outcome and latency; the question text itself stays out of the log.
            audit('copilot-ask', $username, $authGroup, $result['status'] === 200,
                'cid=' . $correlationId . ' state=' . ($answer['state'] ?? '-') . ' iterations=' . ($answer['iterations'] ?? '-')
                . ' tools=' . implode('>', $answer['tool_calls'] ?? []) . ' kept=' . count($answer['claims'] ?? [])
                . ' removed=' . count($answer['removed_claims'] ?? []) . ' ms=' . ($answer['duration_ms'] ?? '-'), $pid);
            respond($result['status'] === 200 ? 200 : 503, $answer ?: ['state' => 'unable_to_answer', 'reason' => 'agent error'], $correlationId);

        case 'feedback':
            $result = $client->post('/session/' . $sessionId . '/feedback', [
                'run_id' => (string) ($input['run_id'] ?? ''),
                'score' => (int) ($input['score'] ?? 0),
                'category' => (string) ($input['category'] ?? 'other'),
            ], $correlationId);
            respond($result['status'] === 200 ? 200 : 503, $result['json'] ?? ['submitted' => false], $correlationId);

        case 'close':
            $result = $client->post('/session/' . $sessionId . '/close', [], $correlationId);
            audit('copilot-close', $username, $authGroup, true, 'cid=' . $correlationId);
            respond(200, $result['json'] ?? ['closed' => false], $correlationId);

        default:
            respond(400, ['state' => 'unable_to_answer', 'reason' => 'unknown action'], $correlationId);
    }
} catch (ScopeDeniedException $e) {
    audit('copilot-scope-denied', $username, $authGroup, false, 'cid=' . $correlationId . ' action=' . $action . ' entry=' . $context, $e->pid);
    respond(403, ['state' => 'access_denied', 'reason' => $context === 'patient'
        ? 'that patient is not assigned to you' : 'that patient is not on your rounding list'], $correlationId);
} catch (\InvalidArgumentException $e) {
    // A bad upload (wrong type, empty file): the caller's problem, said plainly.
    respond(400, ['state' => 'unable_to_answer', 'reason' => 'the document was not accepted: ' . $e->getMessage()], $correlationId);
} catch (AgentUnavailableException $e) {
    error_log('oe-module-copilot-agent: ' . $e->getMessage());
    audit('copilot-agent-unavailable', $username, $authGroup, false, 'cid=' . $correlationId . ' action=' . $action);
    respond(503, ['state' => 'unable_to_answer', 'reason' => 'the co-pilot service is unavailable; retry or review the chart directly'], $correlationId);
} catch (\Throwable $e) {
    error_log('oe-module-copilot-agent: ' . $e::class . ': ' . $e->getMessage());
    respond(500, ['state' => 'unable_to_answer', 'reason' => 'an internal error occurred; retry or review the chart directly'], $correlationId);
}
