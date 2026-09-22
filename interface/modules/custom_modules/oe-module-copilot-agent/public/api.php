<?php

/**
 * JSON endpoint behind the CopilotAgent tab. The browser calls this (same origin,
 * OpenEMR session cookie); this proxies to the agent service over the private network
 * with a signed request. The browser never talks to the agent or the model (PHI4).
 *
 * Actions: open, status, select, ask, feedback, close.
 * Week 2 adds document actions; demo_* are validation tooling, refused unless COPILOT_DEMO_TOOLS is set.
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
use OpenEMR\Modules\CopilotAgent\DemoDocuments;
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

/**
 * Week 2: read a stored document with the agent, then persist what it read. The document stays in
 * the chart whatever happens here; a failed extraction leaves it stored and unprocessed.
 *
 * @return array<string, mixed>
 */
function extractAndPersist(AgentClient $client, DocumentWriter $writer, int $pid, int $docId, string $docType,
                           string $bytes, string $mime, string $filename, int $eid, string $correlationId): array
{
    $result = $client->post('/documents/extract', [
        'pid' => $pid, 'doc_id' => $docId, 'doc_type' => $docType, 'filename' => $filename, 'mime' => $mime,
        'content_base64' => base64_encode($bytes),
    ], $correlationId);
    if ($result['status'] !== 200 || !is_array($result['json'])) {
        return ['processed' => false, 'reason' => 'extraction failed (agent status ' . $result['status'] . ')',
                'detail' => $result['json']['detail'] ?? null];
    }
    $extraction = $result['json'];
    // The document's own claim about whose results these are, checked before any of them become
    // chart data. A misfiled report is refused outright: it stays stored for a human to look at,
    // and nothing it says reaches the patient's record or the brief.
    $document = (array) ($extraction['document'] ?? []);
    $printedName = $docType === 'intake_form'
        ? ($document['demographics']['name']['value'] ?? null)
        : ($document['patient_ref']['value'] ?? null);
    $mismatch = $writer->patientRefMismatch($pid, is_string($printedName) ? $printedName : null);
    if ($mismatch !== null) {
        return ['processed' => false, 'reason' => $mismatch, 'patient_ref_mismatch' => true,
                'unsupported_fields' => $extraction['unsupported_fields'] ?? [],
                'extraction_ms' => $extraction['duration_ms'] ?? null,
                'model' => $extraction['model'] ?? null,
                'agent_correlation_id' => $extraction['correlation_id'] ?? null];
    }
    if ($docType === 'intake_form') {
        // An intake form is someone else's report about the patient: stored beside the form,
        // never merged into the clinical lists.
        $sidecar = $writer->persistIntakeSidecar($pid, $docId, $extraction, $eid);
        return [
            'processed' => true, 'sidecar_doc_id' => $sidecar, 'source_ids' => ['doc:' . $docId], 'skipped' => [],
            'attributed_to' => null,
            'unsupported_fields' => $extraction['unsupported_fields'] ?? [],
            'extraction_ms' => $extraction['duration_ms'] ?? null,
            'model' => $extraction['model'] ?? null,
            'agent_correlation_id' => $extraction['correlation_id'] ?? null,
        ];
    }
    $written = $writer->persistLabDocument($pid, $docId, (array) ($extraction['document'] ?? []), $eid, (string) ($extraction['model'] ?? 'unknown'));
    return $written + [
        'processed' => true,
        'unsupported_fields' => $extraction['unsupported_fields'] ?? [],
        'extraction_ms' => $extraction['duration_ms'] ?? null,
        'model' => $extraction['model'] ?? null,
        'agent_correlation_id' => $extraction['correlation_id'] ?? null,
    ];
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
    if (in_array($action, ['select', 'ask', 'open_patient', 'attach', 'persist_extraction', 'extract', 'documents', 'supervise', 'page', 'demo_generate', 'demo_purge'], true)) {
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
            $outcome = ['processed' => false, 'reason' => 'stored only'];
            if (($input['extract'] ?? '1') !== '0') {
                $outcome = extractAndPersist($client, $writer, $pid, $docId, $docType, (string) file_get_contents((string) $file['tmp_name']),
                    (string) mime_content_type((string) $file['tmp_name']), basename((string) ($file['name'] ?? 'document')),
                    $sessionPid === $pid ? $sessionEncounter : 0, $correlationId);
                audit('copilot-document-extracted', $username, $authGroup, (bool) $outcome['processed'],
                    'cid=' . $correlationId . ' doc=' . $docId . ' type=' . $docType . ' processed=' . (int) $outcome['processed']
                    . ' results=' . count($outcome['source_ids'] ?? []) . ' skipped=' . count($outcome['skipped'] ?? [])
                    . ' unsupported=' . count($outcome['unsupported_fields'] ?? []) . ' ms=' . ($outcome['extraction_ms'] ?? '-'), $pid);
            }
            respond(200, ['doc_id' => $docId, 'doc_type' => $docType] + $outcome, $correlationId);

        case 'extract':
            // Week 2: (re)read a document already in the chart. Idempotent: an extracted document is returned as is.
            $pid = (int) ($input['pid'] ?? 0);
            $docId = (int) ($input['doc_id'] ?? 0);
            $docType = (string) ($input['doc_type'] ?? 'lab_pdf');
            $writer = new DocumentWriter($scope);
            if (!$writer->documentBelongsTo($docId, $pid)) {
                throw new ScopeDeniedException($pid);
            }
            if ($docType === 'intake_form' && ($sidecar = $writer->sidecarFor($docId, $pid)) !== null) {
                respond(200, ['doc_id' => $docId, 'processed' => true, 'already_persisted' => true, 'sidecar_doc_id' => $sidecar], $correlationId);
            }
            $existing = $docType === 'lab_pdf' ? $writer->orderFor($docId) : null;
            if ($existing !== null) {
                respond(200, ['doc_id' => $docId, 'processed' => true, 'already_persisted' => true, 'order_id' => $existing,
                              'source_ids' => $writer->sourceIdsFor($docId)], $correlationId);
            }
            $stored = new \Document($docId);
            $bytes = $stored->get_data();
            if (!is_string($bytes) || $bytes === '') {
                respond(404, ['state' => 'unable_to_answer', 'reason' => 'the stored document could not be read'], $correlationId);
            }
            $outcome = extractAndPersist($client, $writer, $pid, $docId, $docType, $bytes, (string) $stored->get_mimetype(),
                (string) $stored->get_name(), $sessionPid === $pid ? $sessionEncounter : 0, $correlationId);
            audit('copilot-document-extracted', $username, $authGroup, (bool) $outcome['processed'],
                'cid=' . $correlationId . ' doc=' . $docId . ' type=' . $docType . ' processed=' . (int) $outcome['processed']
                . ' results=' . count($outcome['source_ids'] ?? []) . ' skipped=' . count($outcome['skipped'] ?? [])
                . ' unsupported=' . count($outcome['unsupported_fields'] ?? []) . ' ms=' . ($outcome['extraction_ms'] ?? '-'), $pid);
            respond(200, ['doc_id' => $docId, 'doc_type' => $docType, 'already_persisted' => false] + $outcome, $correlationId);

        case 'persist_extraction':
            // Week 2: the module writes what the agent extracted. Idempotent per document.
            $pid = (int) ($input['pid'] ?? 0);
            $docId = (int) ($input['doc_id'] ?? 0);
            $docType = (string) ($input['doc_type'] ?? 'lab_pdf');
            $extraction = is_array($input['extraction'] ?? null) ? $input['extraction'] : null;
            if ($docId <= 0 || $extraction === null) {
                respond(400, ['state' => 'unable_to_answer', 'reason' => 'doc_id and extraction are required'], $correlationId);
            }
            if (!in_array($docType, ['lab_pdf', 'intake_form'], true)) {
                respond(400, ['state' => 'unable_to_answer', 'reason' => 'doc_type must be lab_pdf or intake_form'], $correlationId);
            }
            $writer = new DocumentWriter($scope);
            if ($docType === 'intake_form') {
                $existingSidecar = $writer->sidecarFor($docId, $pid);
                if ($existingSidecar !== null) {
                    respond(200, ['already_persisted' => true, 'sidecar_doc_id' => $existingSidecar, 'source_ids' => ['doc:' . $docId]], $correlationId);
                }
                $sidecar = $writer->persistIntakeSidecar($pid, $docId,
                    ['document' => $extraction, 'unsupported_fields' => $input['unsupported_fields'] ?? [], 'model' => (string) ($input['model'] ?? 'unknown')],
                    $sessionPid === $pid ? $sessionEncounter : 0);
                audit('copilot-extraction-persisted', $username, $authGroup, true,
                    'cid=' . $correlationId . ' doc=' . $docId . ' type=intake_form sidecar=' . $sidecar, $pid);
                respond(200, ['already_persisted' => false, 'sidecar_doc_id' => $sidecar, 'source_ids' => ['doc:' . $docId]], $correlationId);
            }
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

        case 'supervise':
            // Week 2 stage 7: the supervisor graph for one patient. The agent decides and reads;
            // this side lists the documents, hands over their bytes, persists what was read, re-reads
            // the chart and resumes. Every write still happens here, under this session, audited.
            $pid = (int) ($input['pid'] ?? 0);
            $writer = new DocumentWriter($scope);
            $documents = $writer->documents($pid);
            foreach ($documents as &$document) {
                if ($document['processed']) {
                    continue;
                }
                $bytes = (new \Document((int) $document['doc_id']))->get_data();
                if (is_string($bytes) && $bytes !== '') {
                    $document['content_base64'] = base64_encode($bytes);
                }
            }
            unset($document);
            $eid = $sessionPid === $pid ? $sessionEncounter : 0;
            // Several documents may each wait through a rate-limit retry; give the graph room.
            $result = $client->post('/session/' . $sessionId . '/supervise', ['pid' => $pid, 'documents' => $documents], $correlationId, 300);
            if ($result['status'] !== 200 || !is_array($result['json'])) {
                audit('copilot-supervise', $username, $authGroup, false, 'cid=' . $correlationId . ' agent status=' . $result['status'], $pid);
                respond(503, ['state' => 'unable_to_answer', 'reason' => 'the agent could not run the supervisor (status ' . $result['status'] . ')',
                              'detail' => $result['json']['detail'] ?? null], $correlationId);
            }
            $summary = $result['json'];
            if (($summary['phase'] ?? '') === 'extracted') {
                $persisted = [];
                foreach ((array) ($summary['extractions'] ?? []) as $extraction) {
                    $docId = (int) ($extraction['doc_id'] ?? 0);
                    $docType = (string) ($extraction['doc_type'] ?? 'lab_pdf');
                    $extracted = is_array($extraction['result'] ?? null) ? $extraction['result'] : [];
                    // The document's own claim about whose results these are. A report filed under
                    // the wrong patient is refused here, before any of it becomes chart data: it
                    // stays stored for a human, and the brief is told it was not filed.
                    $read = (array) ($extracted['document'] ?? []);
                    $printedName = $docType === 'intake_form'
                        ? ($read['demographics']['name']['value'] ?? null)
                        : ($read['patient_ref']['value'] ?? null);
                    $mismatch = $writer->patientRefMismatch($pid, is_string($printedName) ? $printedName : null);
                    if ($mismatch !== null) {
                        $persisted[] = ['doc_id' => $docId, 'doc_type' => $docType, 'source_ids' => [],
                                        'skipped' => [], 'refused' => $mismatch];
                        audit('copilot-document-refused', $username, $authGroup, false,
                            'cid=' . $correlationId . ' doc=' . $docId . ' type=' . $docType . ' reason=patient_ref_mismatch', $pid);
                        continue;
                    }
                    if ($docType === 'lab_pdf') {
                        $written = $writer->persistLabDocument($pid, $docId, (array) ($extracted['document'] ?? []), $eid, (string) ($extracted['model'] ?? 'unknown'));
                        $persisted[] = ['doc_id' => $docId, 'doc_type' => $docType, 'source_ids' => $written['source_ids'],
                                        'order_id' => $written['order_id'], 'skipped' => $written['skipped']];
                        $note = 'results=' . count($written['source_ids']) . ' skipped=' . count($written['skipped']) . ' attributed=' . $written['attributed_to'];
                    } else {
                        $sidecar = $writer->persistIntakeSidecar($pid, $docId, $extracted, $eid);
                        $persisted[] = ['doc_id' => $docId, 'doc_type' => $docType, 'source_ids' => ['doc:' . $docId], 'sidecar_doc_id' => $sidecar, 'skipped' => []];
                        $note = 'sidecar=' . $sidecar;
                    }
                    audit('copilot-document-extracted', $username, $authGroup, true,
                        'cid=' . $correlationId . ' doc=' . $docId . ' type=' . $docType . ' processed=1 ' . $note
                        . ' unsupported=' . count($extracted['unsupported_fields'] ?? []), $pid);
                }
                // The chart as it is now, with the new rows, is what the brief is generated from.
                $appointment = null;
                foreach ($scope->roundingList(date('Y-m-d')) as $booked) {
                    if ($booked['pid'] === $pid) {
                        $appointment = $booked;
                        break;
                    }
                }
                $chart = (new ChartReader($scope, $config))->read($pid, $appointment);
                $result = $client->post('/session/' . $sessionId . '/supervise/resume',
                    ['pid' => $pid, 'persisted' => $persisted, 'chart' => $chart], $correlationId, 300);
                if ($result['status'] !== 200 || !is_array($result['json'])) {
                    audit('copilot-supervise', $username, $authGroup, false, 'cid=' . $correlationId . ' resume agent status=' . $result['status'], $pid);
                    respond(503, ['state' => 'unable_to_answer', 'reason' => 'the agent could not finish after persistence (status ' . $result['status'] . ')',
                                  'detail' => $result['json']['detail'] ?? null, 'persisted' => $persisted], $correlationId);
                }
                $summary = $result['json'] + ['persisted' => $persisted];
            }
            $brief = $summary['brief'] ?? null;
            audit('copilot-supervise', $username, $authGroup, ($summary['phase'] ?? '') === 'done',
                'cid=' . $correlationId . ' documents=' . count($documents) . ' unread=' . count(array_filter($documents, static fn(array $d): bool => !$d['processed']))
                . ' read=' . count($summary['extractions'] ?? []) . ' failed=' . count($summary['failed'] ?? []) . ' changes=' . count($summary['changes'] ?? [])
                . ' handoffs=' . count($summary['handoffs'] ?? []) . ' state=' . ($brief['state'] ?? '-') . ' brief_ms=' . ($brief['duration_ms'] ?? '-'), $pid);
            respond(200, ['documents' => array_map(static function (array $d): array { unset($d['content_base64']); return $d; }, $documents)] + $summary, $correlationId);

        case 'page':
            // Week 2 stage 9: click-to-source. The page a citation points at, as an image, with the
            // quoted text boxed where the PDF's own text layer places it. Viewing is audited: it is
            // a read of the patient's document.
            $pid = (int) ($input['pid'] ?? 0);
            $docId = (int) ($input['doc_id'] ?? 0);
            $pageNumber = max(1, (int) ($input['page'] ?? 1));
            $quotes = array_values(array_filter(array_map('strval', (array) ($input['quotes'] ?? [])), static fn(string $q): bool => $q !== ''));
            $writer = new DocumentWriter($scope);
            if (!$writer->documentBelongsTo($docId, $pid)) {
                throw new ScopeDeniedException($pid);
            }
            $stored = new \Document($docId);
            $bytes = $stored->get_data();
            if (!is_string($bytes) || $bytes === '') {
                respond(404, ['state' => 'unable_to_answer', 'reason' => 'the stored document could not be read'], $correlationId);
            }
            $result = $client->post('/documents/page', ['pid' => $pid, 'doc_id' => $docId, 'page' => $pageNumber,
                'quotes' => array_slice($quotes, 0, 20), 'content_base64' => base64_encode($bytes)], $correlationId);
            audit('copilot-document-viewed', $username, $authGroup, $result['status'] === 200,
                'cid=' . $correlationId . ' doc=' . $docId . ' page=' . $pageNumber . ' quotes=' . count($quotes), $pid);
            if ($result['status'] !== 200 || !is_array($result['json'])) {
                respond($result['status'] >= 400 && $result['status'] < 500 ? 400 : 503,
                    ['state' => 'unable_to_answer', 'reason' => 'the page could not be rendered', 'detail' => $result['json']['detail'] ?? null], $correlationId);
            }
            respond(200, ['doc_id' => $docId, 'original_url' => '/controller.php?document&retrieve&patient_id=' . $pid . '&document_id=' . $docId . '&as_file=false']
                + $result['json'], $correlationId);

        case 'documents':
            // Week 2: the patient's lab reports and intake forms and whether each has been read.
            $pid = (int) ($input['pid'] ?? 0);
            $documents = (new DocumentWriter($scope))->documents($pid);
            respond(200, ['pid' => $pid, 'documents' => $documents,
                          'unprocessed' => count(array_filter($documents, static fn(array $d): bool => !$d['processed']))], $correlationId);

        // -- Validation tooling. Removing this block and src/DemoDocuments.php removes the
        // feature. Refuses outright unless the environment turned it on, so the UI being hidden
        // is never the only thing standing between a caller and these actions.
        case 'demo_generate':
        case 'demo_purge':
        case 'demo_files':
        case 'demo_file':
            if (!$config->demoTools) {
                respond(403, ['state' => 'access_denied', 'reason' => 'demo tooling is not enabled on this instance'], $correlationId);
            }
            $demo = new DemoDocuments($scope, $openemrRoot);
            $pid = (int) ($input['pid'] ?? $_GET['pid'] ?? 0);

            if ($action === 'demo_files') {
                respond(200, ['files' => $demo->files(), 'directory' => $demo->directory()], $correlationId);
            }
            if ($action === 'demo_file') {
                $name = (string) ($_GET['name'] ?? '');
                $bytes = $demo->read($name);        // matched against the listing, never used as a path
                audit('copilot-demo-downloaded', $username, $authGroup, true, 'cid=' . $correlationId . ' file=' . $name, $pid);
                header('Content-Type: application/pdf');
                header('Content-Disposition: attachment; filename="' . $name . '"');
                header('Content-Length: ' . strlen($bytes));
                echo $bytes;
                exit;
            }
            if ($action === 'demo_generate') {
                $written = $demo->generate($pid, (string) ($input['variant'] ?? 'abnormal'), $scope->displayName());
                audit('copilot-demo-generated', $username, $authGroup, true,
                    'cid=' . $correlationId . ' variant=' . (string) ($input['variant'] ?? 'abnormal')
                    . ' files=' . count($written), $pid);
                respond(200, ['generated' => $written, 'files' => $demo->files(), 'directory' => $demo->directory()], $correlationId);
            }
            $purged = $demo->purge($pid);
            audit('copilot-demo-purged', $username, $authGroup, true,
                'cid=' . $correlationId . ' files=' . $purged['files'] . ' documents=' . $purged['documents']
                . ' results=' . $purged['results'], $pid);
            respond(200, $purged + ['files_remaining' => $demo->files(), 'directory' => $demo->directory()], $correlationId);

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
