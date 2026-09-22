<?php

/**
 * The module's only write path (Week 2).
 *
 * The agent never writes. It returns an extraction; this class stores the source document in
 * the patient's Documents and the extracted lab values in OpenEMR's own lab chain
 * (procedure_order -> procedure_order_code -> procedure_report -> procedure_result), which is
 * what FhirObservationService and Lab Overview read. Every row carries its provenance:
 * procedure_result.document_id points at the source document, result_status is 'preliminary',
 * review_status is 'received', and the order is marked history_order with external_id doc:<id>.
 *
 * Nothing here is clinician-confirmed and nothing pretends to be.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Uuid\UuidRegistry;
use OpenEMR\Services\DocumentService;

final class DocumentWriter
{
    // DocumentService::isValidPath() matches each part against the category name lowercased with
    // spaces removed (underscores are stripped from the part), so the seeded "Lab Report" and
    // "Medical Record" categories are addressed like this.
    public const CATEGORY_LAB = '/categories/lab_report';
    public const CATEGORY_RECORD = '/categories/medical_record';

    /** Pseudo-provider that owns imported orders whose ordering provider is not the signed-in user. */
    public const IMPORT_USERNAME = 'docimport';

    /** Seeded procedure_providers row "External Lab"; the extracted lab name goes in procedure_result.facility. */
    private const EXTERNAL_LAB_PPID = 2;

    private const ALLOWED_MIME = ['application/pdf', 'image/png', 'image/jpeg'];

    /**
     * Exact test name to LOINC. Lab Overview lists results by result_code, so an unmapped test keeps
     * its name in result_text and stays out of that view. Exact match only: the name is model output,
     * and a fuzzy match would file a value under the wrong test.
     */
    private const LOINC = [
        'potassium' => '2823-3', 'sodium' => '2951-2', 'chloride' => '2075-0', 'bicarbonate' => '1963-8',
        'creatinine' => '2160-0', 'bun' => '3094-0', 'blood urea nitrogen' => '3094-0', 'glucose' => '2345-7',
        'calcium' => '17861-6', 'magnesium' => '19123-9', 'egfr' => '33914-3',
        'hemoglobin' => '718-7', 'hematocrit' => '4544-3', 'wbc' => '6690-2', 'white blood cell count' => '6690-2',
        'platelets' => '777-3', 'platelet count' => '777-3',
        'hba1c' => '4548-4', 'hemoglobin a1c' => '4548-4', 'a1c' => '4548-4',
        'total cholesterol' => '2093-3', 'cholesterol' => '2093-3', 'ldl' => '13457-7', 'ldl cholesterol' => '13457-7',
        'hdl' => '2085-9', 'hdl cholesterol' => '2085-9', 'triglycerides' => '2571-8',
        'tsh' => '3016-3', 'alt' => '1742-6', 'ast' => '1920-8',
    ];

    public function __construct(private readonly PanelScope $scope)
    {
    }

    /** Store an uploaded file in the patient's Documents. Returns the new documents.id. */
    public function storeDocument(int $pid, string $tmpPath, string $filename, string $mime, string $categoryPath, int $eid): int
    {
        $this->scope->assertInScope($pid);
        if (!in_array($mime, self::ALLOWED_MIME, true)) {
            throw new \InvalidArgumentException('unsupported document type');
        }
        $service = new DocumentService();
        if (!$service->isValidPath($categoryPath)) {
            throw new \RuntimeException('document category does not exist');
        }
        $categoryId = (int) $service->getLastIdOfPath($categoryPath);
        $bytes = file_get_contents($tmpPath);
        if ($bytes === false || $bytes === '') {
            throw new \InvalidArgumentException('empty document');
        }
        $document = new \Document();
        $error = $document->createDocument($pid, $categoryId, $filename, $mime, $bytes, eid: $eid);
        if (!empty($error)) {
            throw new \RuntimeException('document could not be stored');
        }
        return (int) $document->get_id();
    }

    /** Rule 2: a document is only ever read for the patient it is filed under. */
    public function documentBelongsTo(int $docId, int $pid): bool
    {
        $row = QueryUtils::fetchRecords('SELECT foreign_id FROM documents WHERE id = ? AND deleted = 0', [$docId]);
        return !empty($row) && (int) $row[0]['foreign_id'] === $pid;
    }

    /** The order already written for this document, or null. procedure_result.document_id is the link. */
    public function orderFor(int $docId): ?int
    {
        $row = QueryUtils::fetchRecords(
            'SELECT pr.procedure_order_id FROM procedure_result prs '
            . 'JOIN procedure_report pr ON pr.procedure_report_id = prs.procedure_report_id '
            . 'WHERE prs.document_id = ? LIMIT 1',
            [$docId]
        );
        return empty($row) ? null : (int) $row[0]['procedure_order_id'];
    }

    /** Name of the sidecar document that holds a document's extraction. */
    public static function sidecarName(int $docId): string
    {
        return 'copilot-extraction-' . $docId . '.json';
    }

    /** The sidecar already stored for this document, or null. */
    public function sidecarFor(int $docId, int $pid): ?int
    {
        $row = QueryUtils::fetchRecords(
            'SELECT id FROM documents WHERE foreign_id = ? AND name = ? AND deleted = 0 ORDER BY id DESC LIMIT 1',
            [$pid, self::sidecarName($docId)]
        );
        return empty($row) ? null : (int) $row[0]['id'];
    }

    /** Whether a document has been read: a lab report has an order, an intake form has a sidecar. */
    public function isProcessed(int $docId, int $pid, string $docType): bool
    {
        return $docType === 'lab_pdf' ? $this->orderFor($docId) !== null : $this->sidecarFor($docId, $pid) !== null;
    }

    /**
     * Persist an intake form's extraction as a sidecar document beside the form, under Medical
     * Record. Nothing is written to the clinical lists: what a form says a patient takes or reacts
     * to is a report, not a reconciled record, and the brief presents it as such.
     *
     * @param array<string, mixed> $extraction the ExtractionResult as JSON
     */
    public function persistIntakeSidecar(int $pid, int $docId, array $extraction, int $eid): int
    {
        $this->scope->assertInScope($pid);
        if (!$this->documentBelongsTo($docId, $pid)) {
            throw new ScopeDeniedException($pid);
        }
        $existing = $this->sidecarFor($docId, $pid);
        if ($existing !== null) {
            return $existing;
        }
        $service = new DocumentService();
        $categoryId = (int) $service->getLastIdOfPath(self::CATEGORY_RECORD);
        $payload = ['source_document_id' => $docId, 'doc_type' => 'intake_form', 'persisted_at' => gmdate('c')] + $extraction;
        $bytes = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
        if (!is_string($bytes)) {
            throw new \RuntimeException('extraction could not be encoded');
        }
        $document = new \Document();
        $error = $document->createDocument($pid, $categoryId, self::sidecarName($docId), 'application/json', $bytes, eid: $eid);
        if (!empty($error)) {
            throw new \RuntimeException('extraction sidecar could not be stored');
        }
        return (int) $document->get_id();
    }

    /**
     * The patient's lab reports and intake forms with whether each has been read (Week 2, stage 7).
     * Sidecars are excluded: they are extractions, not documents to read. Category decides the type.
     *
     * @return list<array{doc_id: int, doc_type: string, name: string, date: string, processed: bool}>
     */
    public function documents(int $pid): array
    {
        $this->scope->assertInScope($pid);
        $rows = QueryUtils::fetchRecords(
            'SELECT d.id, d.name, d.date, d.docdate, c.name AS category FROM documents d '
            . 'JOIN categories_to_documents cd ON cd.document_id = d.id JOIN categories c ON c.id = cd.category_id '
            . 'WHERE d.foreign_id = ? AND d.deleted = 0 AND c.name IN (?, ?) AND d.name NOT LIKE ? ORDER BY d.id',
            [$pid, 'Lab Report', 'Medical Record', 'copilot-extraction-%']
        );
        $out = [];
        foreach ($rows as $row) {
            $docId = (int) $row['id'];
            $docType = $row['category'] === 'Lab Report' ? 'lab_pdf' : 'intake_form';
            $out[] = [
                'doc_id' => $docId, 'doc_type' => $docType, 'name' => (string) $row['name'],
                'date' => substr((string) ($row['docdate'] ?: $row['date']), 0, 10),
                'processed' => $this->isProcessed($docId, $pid, $docType),
            ];
        }
        return $out;
    }

    /** @return list<string> */
    public function sourceIdsFor(int $docId): array
    {
        $rows = QueryUtils::fetchRecords('SELECT procedure_result_id FROM procedure_result WHERE document_id = ? ORDER BY procedure_result_id', [$docId]);
        return array_map(static fn(array $r): string => 'lab:' . (int) $r['procedure_result_id'], $rows);
    }

    /**
     * Write one lab document's results. One transaction; a partial chain is never left behind.
     *
     * @param array<string, mixed> $doc a LabDocument as JSON (copilot/documents/schemas.py)
     * @return array{order_id: int, source_ids: list<string>, skipped: list<array{index: int, reason: string}>, attributed_to: string}
     */
    public function persistLabDocument(int $pid, int $docId, array $doc, int $eid, string $model): array
    {
        $this->scope->assertInScope($pid);
        if (!$this->documentBelongsTo($docId, $pid)) {
            throw new ScopeDeniedException($pid);
        }
        [$providerId, $attributedTo] = $this->orderingProvider(self::field($doc, 'ordering_provider'));

        $results = [];
        $skipped = [];
        foreach ((array) ($doc['results'] ?? []) as $index => $result) {
            $reason = is_array($result) ? self::unusable($result) : 'result is not an object';
            if ($reason !== null) {
                $skipped[] = ['index' => (int) $index, 'reason' => $reason];
                continue;
            }
            $results[] = $result;
        }

        $reportDate = self::value(self::field($doc, 'report_date')) ?? date('Y-m-d');
        $collected = self::firstValue($results, 'collection_date') ?? $reportDate;
        $facility = self::value(self::field($doc, 'performing_lab')) ?? '';

        QueryUtils::startTransaction();
        try {
            $orderId = (int) QueryUtils::sqlInsert(
                'INSERT INTO procedure_order (uuid, provider_id, patient_id, encounter_id, date_collected, date_ordered, '
                . 'order_status, activity, lab_id, procedure_order_type, history_order, external_id, clinical_hx) '
                . 'VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)',
                [
                    (new UuidRegistry(['table_name' => 'procedure_order']))->createUuid(),
                    $providerId, $pid, $eid, $collected, $reportDate, 'completed', self::EXTERNAL_LAB_PPID,
                    'laboratory_test', '1', 'doc:' . $docId,
                    'Imported from a lab document by the co-pilot. Values machine-extracted; not clinician-verified.',
                ]
            );
            QueryUtils::sqlStatementThrowException(
                'INSERT INTO procedure_order_code (procedure_order_id, procedure_order_seq, procedure_code, procedure_name, '
                . 'procedure_source, procedure_type) VALUES (?, 1, ?, ?, ?, ?)',
                [$orderId, 'COPILOT-DOC', 'Lab report imported from document', '1', 'laboratory_test']
            );
            $reportId = (int) QueryUtils::sqlInsert(
                'INSERT INTO procedure_report (uuid, procedure_order_id, procedure_order_seq, date_collected, date_report, '
                . 'source, report_status, review_status, report_notes) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)',
                [
                    (new UuidRegistry(['table_name' => 'procedure_report']))->createUuid(),
                    $orderId, $collected, $reportDate, $this->scope->userId(),
                    // The lab finalised its report; nobody here has reviewed the extraction of it.
                    'final', 'received',
                    'Values machine-extracted from doc:' . $docId . ' by ' . $model . '. Pending clinician review.',
                ]
            );

            $sourceIds = [];
            foreach ($results as $result) {
                $name = (string) self::value($result['test_name']);
                $value = (string) self::value($result['value']);
                $confidence = (float) ($result['value']['confidence'] ?? 0);
                $page = (string) ($result['value']['citation']['page'] ?? '?');
                $resultId = (int) QueryUtils::sqlInsert(
                    'INSERT INTO procedure_result (uuid, procedure_report_id, result_data_type, result_code, result_text, date, '
                    . 'facility, units, result, `range`, abnormal, comments, document_id, result_status) '
                    . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    [
                        (new UuidRegistry(['table_name' => 'procedure_result']))->createUuid(),
                        $reportId, is_numeric($value) ? 'N' : 'S', self::loinc($name), $name,
                        self::value(self::field($result, 'collection_date')) ?? $collected,
                        $facility, self::value(self::field($result, 'unit')) ?? '', $value,
                        self::value(self::field($result, 'reference_range')) ?? '',
                        self::abnormal(self::value(self::field($result, 'abnormal_flag'))),
                        sprintf('machine-extracted from doc:%d page %s, confidence %.2f, model %s; not clinician-verified',
                            $docId, $page, $confidence, $model),
                        $docId, 'preliminary',
                    ]
                );
                $sourceIds[] = 'lab:' . $resultId;
            }
            QueryUtils::commitTransaction();
        } catch (\Throwable $e) {
            QueryUtils::rollbackTransaction();
            throw $e;
        }

        return ['order_id' => $orderId, 'source_ids' => $sourceIds, 'skipped' => $skipped, 'attributed_to' => $attributedTo];
    }

    /** The users row that owns imported orders nobody here ordered. Created on first use; cannot sign in. */
    public function importProviderId(): int
    {
        $row = QueryUtils::fetchRecords('SELECT id FROM users WHERE username = ?', [self::IMPORT_USERNAME]);
        if (!empty($row)) {
            return (int) $row[0]['id'];
        }
        return (int) QueryUtils::sqlInsert(
            'INSERT INTO users (uuid, username, fname, lname, authorized, active, see_auth, calendar) VALUES (?, ?, ?, ?, 0, 0, 0, 0)',
            [(new UuidRegistry(['table_name' => 'users']))->createUuid(), self::IMPORT_USERNAME, 'Document', 'Import']
        );
    }

    // -- helpers over the extraction JSON --------------------------------------------------

    /**
     * Exact match against the signed-in user only. The name is model output, and a fuzzy match
     * would attribute an order to a clinician who never placed it.
     *
     * @param array<string, mixed>|null $field
     * @return array{0: int, 1: string}
     */
    private function orderingProvider(?array $field): array
    {
        $name = self::value($field);
        if ($name !== null && self::normalize($name) === self::normalize($this->scope->displayName())) {
            return [$this->scope->userId(), 'hospitalist'];
        }
        return [$this->importProviderId(), 'import'];
    }

    /** @param array<string, mixed> $owner */
    private static function field(array $owner, string $key): ?array
    {
        $field = $owner[$key] ?? null;
        return is_array($field) ? $field : null;
    }

    /** A supported field's value: present, cited, with confidence above zero. Anything else is null. */
    private static function value(?array $field): ?string
    {
        if ($field === null || !isset($field['value']) || $field['value'] === '') {
            return null;
        }
        if (empty($field['citation']) || (float) ($field['confidence'] ?? 0) <= 0) {
            return null;
        }
        return (string) $field['value'];
    }

    /** Why a result cannot be persisted, or null. The test name and the value are the minimum. */
    private static function unusable(array $result): ?string
    {
        foreach (['test_name', 'value'] as $key) {
            $field = self::field($result, $key);
            if ($field === null || !isset($field['value']) || $field['value'] === '') {
                return $key . ' is unsupported';
            }
            if (empty($field['citation'])) {
                return $key . ' has no citation';
            }
            if ((float) ($field['confidence'] ?? 0) <= 0) {
                return $key . ' has no confidence';
            }
        }
        return null;
    }

    /** @param list<array<string, mixed>> $results */
    private static function firstValue(array $results, string $key): ?string
    {
        foreach ($results as $result) {
            $value = self::value(self::field($result, $key));
            if ($value !== null) {
                return $value;
            }
        }
        return null;
    }

    /** What the report said, in OpenEMR's vocabulary (no, yes, high, low). Data, not a judgement. */
    private static function abnormal(?string $flag): string
    {
        return match (strtoupper(trim((string) $flag))) {
            'H', 'HIGH' => 'high',
            'L', 'LOW' => 'low',
            'N', 'NORMAL' => 'no',
            'A', 'ABNORMAL', 'Y', 'YES' => 'yes',
            default => '',
        };
    }

    private static function loinc(string $name): string
    {
        return self::LOINC[self::normalize($name)] ?? '';
    }

    private static function normalize(string $text): string
    {
        return strtolower(trim((string) preg_replace('/\s+/', ' ', $text)));
    }
}
