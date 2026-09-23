<?php

/**
 * Reads one patient's chart through OpenEMR's service layer into the compact JSON the
 * agent consumes (copilot/copilot/schemas.py: Chart).
 *
 * Design notes, all traceable to AUDIT.md / USER.md:
 * - Every read is preceded by PanelScope::assertInScope() (REQ-SCOPE-1, fails closed).
 * - Each domain is read separately with its own timing and status so a failed source
 *   becomes a "partial" response, never a silent omission (PRD FR17/FR20).
 * - Only the fields the brief needs are sent (REQ-MIN-1, PHI3), with default date windows
 *   on labs and encounters (AUDIT D8) plus the latest result per test regardless of age.
 * - Prescriptions are read with a narrow query because PrescriptionService drops
 *   end_date from its result set and the agent derives status from it (AUDIT D1).
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
use OpenEMR\Services\EncounterService;
use OpenEMR\Services\ImmunizationService;
use OpenEMR\Services\ListService;
use OpenEMR\Services\ObservationLabService;
use OpenEMR\Services\PatientService;
use OpenEMR\Services\Search\TokenSearchField;
use OpenEMR\Services\VitalsService;

final class ChartReader
{
    public function __construct(
        private readonly PanelScope $scope,
        private readonly Config $config,
    ) {
    }

    /**
     * @param array{pid:int,eid:int,time:string,title:string,status:string}|null $appointment
     * @return array<string, mixed>
     */
    public function read(int $pid, ?array $appointment = null): array
    {
        $this->scope->assertInScope($pid);

        $patient = (new PatientService())->findByPid($pid);
        if (!is_array($patient) || empty($patient['uuid'])) {
            throw new \RuntimeException('patient record not readable');
        }
        $puuid = UuidRegistry::uuidToString($patient['uuid']);
        $sources = [];

        $chart = [
            'schema_version' => '1.0',
            'generated_at' => gmdate('Y-m-d\TH:i:s\Z'),
            'patient' => [
                'pid' => $pid,
                'uuid' => $puuid,
                'name' => trim(((string) ($patient['fname'] ?? '')) . ' ' . ((string) ($patient['lname'] ?? ''))),
                'dob' => self::date($patient['DOB'] ?? null),
                'age' => self::age($patient['DOB'] ?? null),
                'sex' => (string) ($patient['sex'] ?? ''),
                'pubpid' => (string) ($patient['pubpid'] ?? ''),
                'provider_id' => (int) ($patient['providerID'] ?? 0),
                'source_id' => 'patient:' . $pid,
            ],
            'appointment' => $appointment === null ? null : [
                'eid' => $appointment['eid'],
                'date' => date('Y-m-d'),
                'time' => $appointment['time'],
                'title' => $appointment['title'],
                'status' => $appointment['status'],
                'source_id' => 'appointment:' . $appointment['eid'],
            ],
        ];

        $chart['problems'] = $this->section('problems', fn(): array => $this->problems($pid), $sources);
        $chart['medications'] = $this->section('medications', fn(): array => $this->medications($pid), $sources);
        $chart['allergies'] = $this->section('allergies', fn(): array => $this->allergies($pid), $sources);
        $chart['labs'] = $this->section('labs', fn(): array => $this->labs($puuid), $sources);
        $chart['encounters'] = $this->section('encounters', fn(): array => $this->encounters($pid), $sources);
        $chart['immunizations'] = $this->section('immunizations', fn(): array => $this->immunizations($puuid), $sources);
        $chart['vitals'] = $this->section('vitals', fn(): array => $this->vitals($puuid), $sources);
        // Week 2: the lab reports and intake forms on file, and for an intake form the facts read
        // out of it. Without this the agent could answer about a lab value that came from a
        // document but not about the document, and never about an intake form at all -- its facts
        // are deliberately kept out of the clinical lists, so the sidecar is the only place they
        // exist. Bytes stay out: this is a manifest, not the documents themselves.
        $chart['documents'] = $this->section('documents', fn(): array => $this->documents($pid), $sources);
        $chart['sources'] = $sources;

        return $chart;
    }

    /**
     * Run one domain read, recording status and timing. A failure is recorded, not thrown:
     * the response state machine downstream turns it into "partial".
     *
     * @param callable(): list<array<string, mixed>> $read
     * @param array<string, array<string, mixed>> $sources
     * @return list<array<string, mixed>>
     */
    /**
     * Lab reports and intake forms on file, newest first, with what was read out of each.
     *
     * An intake form's facts live in a sidecar document rather than in the chart's lists, because
     * a form is someone else's report about the patient and is not reconciled. That makes the
     * sidecar the only place they exist, so it is read back here and offered as `reported`, whose
     * name is meant to keep saying what it is every time anyone looks at it.
     *
     * @return list<array<string, mixed>>
     */
    private function documents(int $pid): array
    {
        $writer = new DocumentWriter($this->scope);
        $out = [];
        foreach ($writer->documents($pid) as $document) {
            $docId = (int) $document['doc_id'];
            $entry = [
                'source_id' => 'doc:' . $docId,
                'doc_id' => $docId,
                'doc_type' => $document['doc_type'],
                'name' => $document['name'],
                'date' => $document['date'],
                'processed' => (bool) $document['processed'],
                'results' => count($writer->sourceIdsFor($docId)),
            ];
            if ($document['doc_type'] === 'intake_form' && $document['processed']) {
                // Only when there is something: an empty PHP array encodes as [] rather than {},
                // and the chart schema expects an object, so an intake form with nothing readable
                // in it rejected the whole chart on the way back.
                $facts = $this->intakeFacts($writer, $docId, $pid);
                if ($facts !== []) {
                    $entry['reported'] = $facts;
                }
            }
            $out[] = $entry;
        }
        usort($out, static fn(array $a, array $b): int => $b['doc_id'] <=> $a['doc_id']);
        return $out;
    }

    /**
     * The facts an intake form reported, from its sidecar. Reported, never reconciled.
     *
     * @return array<string, mixed>
     */
    private function intakeFacts(DocumentWriter $writer, int $docId, int $pid): array
    {
        $sidecarId = $writer->sidecarFor($docId, $pid);
        if ($sidecarId === null) {
            return [];
        }
        $bytes = (new \Document($sidecarId))->get_data();
        $payload = is_string($bytes) ? json_decode($bytes, true) : null;
        $document = is_array($payload) ? (array) ($payload['document'] ?? []) : [];
        $values = static function (array $items): array {
            $out = [];
            foreach ($items as $item) {
                $value = is_array($item) ? ($item['value'] ?? null) : null;
                if (is_string($value) && $value !== '') {
                    $out[] = $value;
                }
            }
            return $out;
        };
        $single = static fn(array $field): ?string => is_string($field['value'] ?? null) && $field['value'] !== '' ? $field['value'] : null;
        return array_filter([
            'chief_concern' => $single((array) ($document['chief_concern'] ?? [])),
            'form_date' => $single((array) ($document['form_date'] ?? [])),
            'medications' => $values((array) ($document['current_medications'] ?? [])),
            'allergies' => $values((array) ($document['allergies'] ?? [])),
            'family_history' => $values((array) ($document['family_history'] ?? [])),
        ], static fn($v): bool => $v !== null && $v !== []);
    }

    private function section(string $name, callable $read, array &$sources): array
    {
        $started = microtime(true);
        try {
            $rows = $read();
            $sources[$name] = [
                'status' => $rows === [] ? 'empty' : 'ok',
                'count' => count($rows),
                'ms' => (int) round((microtime(true) - $started) * 1000),
            ];
            return $rows;
        } catch (\Throwable $e) {
            error_log('oe-module-copilot-agent: ' . $name . ' read failed: ' . $e::class);
            $sources[$name] = [
                'status' => 'error',
                'count' => 0,
                'ms' => (int) round((microtime(true) - $started) * 1000),
                'detail' => $e::class,
            ];
            return [];
        }
    }

    /** @return list<array<string, mixed>> */
    private function problems(int $pid): array
    {
        $out = [];
        foreach ((new ListService())->getAll($pid, 'medical_problem') as $row) {
            $out[] = [
                'source_id' => 'problem:' . (int) $row['id'],
                'uuid' => (string) ($row['uuid'] ?? ''),
                'title' => (string) ($row['title'] ?? ''),
                'code' => (string) ($row['diagnosis'] ?? ''),
                'begdate' => self::date($row['begdate'] ?? null),
                'enddate' => self::date($row['enddate'] ?? null),
                'outcome' => (string) ($row['outcome'] ?? ''),
                'date' => self::date($row['date'] ?? null),
                'modifydate' => self::date($row['modifydate'] ?? null),
                'comments' => (string) ($row['comments'] ?? ''),
            ];
        }
        return $out;
    }

    /** @return list<array<string, mixed>> */
    private function allergies(int $pid): array
    {
        $out = [];
        foreach ((new ListService())->getAll($pid, 'allergy') as $row) {
            $out[] = [
                'source_id' => 'allergy:' . (int) $row['id'],
                'uuid' => (string) ($row['uuid'] ?? ''),
                'title' => (string) ($row['title'] ?? ''),
                'reaction' => (string) ($row['reaction'] ?? ''),
                'severity' => (string) ($row['severity_al'] ?? ''),
                'begdate' => self::date($row['begdate'] ?? null),
                'enddate' => self::date($row['enddate'] ?? null),
                'comments' => (string) ($row['comments'] ?? ''),
            ];
        }
        return $out;
    }

    /** @return list<array<string, mixed>> */
    private function medications(int $pid): array
    {
        $rows = QueryUtils::fetchRecords(
            'SELECT id, uuid, drug, rxnorm_drugcode, dosage, unit, `interval`, route, start_date, end_date, active, date_added, note'
            . ' FROM prescriptions WHERE patient_id = ? ORDER BY date_added DESC',
            [$pid]
        );
        $out = [];
        foreach ($rows as $row) {
            $out[] = [
                'source_id' => 'prescription:' . (int) $row['id'],
                'uuid' => !empty($row['uuid']) ? UuidRegistry::uuidToString($row['uuid']) : '',
                'drug' => (string) ($row['drug'] ?? ''),
                'rxnorm' => (string) ($row['rxnorm_drugcode'] ?? ''),
                'dosage' => self::str($row['dosage'] ?? null),
                'unit' => self::str($row['unit'] ?? null),
                'interval' => self::str($row['interval'] ?? null),
                'route' => self::str($row['route'] ?? null),
                'start_date' => self::date($row['start_date'] ?? null),
                'end_date' => self::date($row['end_date'] ?? null),
                'active' => (int) ($row['active'] ?? 0),
                'date_added' => self::date($row['date_added'] ?? null),
                'note' => (string) ($row['note'] ?? ''),
            ];
        }
        return $out;
    }

    /** @return list<array<string, mixed>> */
    private function labs(string $puuid): array
    {
        $result = (new ObservationLabService())->search([
            'puuid' => new TokenSearchField('puuid', [$puuid], true),
        ]);
        $cutoff = date('Y-m-d', strtotime('-' . $this->config->labHistoryDays . ' days'));
        $latestPerCode = [];
        $recent = [];
        foreach ($result->getData() as $row) {
            $record = [
                'source_id' => 'lab:' . (int) $row['procedure_result_id'],
                'uuid' => (string) ($row['uuid'] ?? ''),
                'code' => (string) ($row['result_code'] ?? ''),
                'test' => (string) ($row['result_text'] ?? ''),
                'value' => self::str($row['result'] ?? null),
                'units' => self::str($row['units'] ?? null),
                'range' => (string) ($row['range'] ?? ''),
                'abnormal' => (string) ($row['abnormal'] ?? ''),
                'date' => self::date($row['date_report'] ?? null),
                'status' => (string) ($row['result_status'] ?? ''),
                'order_name' => (string) ($row['procedure_name'] ?? ''),
                // Week 2: a machine-read result names its document and page (DocumentWriter writes both).
                'document_id' => ((int) ($row['document_id'] ?? 0)) ?: null,
                'page' => self::pageFromComments((string) ($row['comments'] ?? '')),
            ];
            $code = $record['code'] !== '' ? $record['code'] : $record['test'];
            if (!isset($latestPerCode[$code]) || strcmp((string) $record['date'], (string) $latestPerCode[$code]['date']) > 0) {
                $latestPerCode[$code] = $record;
            }
            if ((string) $record['date'] >= $cutoff) {
                $recent[$record['source_id']] = $record;
            }
        }
        foreach ($latestPerCode as $record) {
            $recent[$record['source_id']] = $record;
        }
        $out = array_values($recent);
        usort($out, static fn(array $a, array $b): int => strcmp((string) $b['date'], (string) $a['date']));
        return $out;
    }

    /** The page DocumentWriter recorded in a result's comment ("... page 2, ..."), or null. */
    private static function pageFromComments(string $comments): ?int
    {
        return preg_match('/page ([0-9]+)/', $comments, $m) === 1 ? (int) $m[1] : null;
    }

    /** @return list<array<string, mixed>> */
    private function encounters(int $pid): array
    {
        $rows = (new EncounterService())->getEncountersForPatientByPid($pid);
        usort($rows, static fn(array $a, array $b): int => strcmp((string) ($b['date'] ?? ''), (string) ($a['date'] ?? '')));
        $cutoff = date('Y-m-d', strtotime('-' . $this->config->encounterHistoryDays . ' days'));
        $out = [];
        foreach ($rows as $index => $row) {
            $date = self::date($row['date'] ?? null);
            if ($index >= 5 && (string) $date < $cutoff) {
                continue; // always keep the latest five, then only the configured window (AUDIT D8)
            }
            $out[] = [
                'source_id' => 'encounter:' . (int) $row['eid'],
                'uuid' => (string) ($row['euuid'] ?? ''),
                'date' => $date,
                'reason' => (string) ($row['reason'] ?? ''),
                'category' => (string) ($row['pc_catname'] ?? ''),
                'class_code' => (string) ($row['class_code'] ?? ''),
                'provider' => (string) ($row['provider_username'] ?? ''),
                'facility' => (string) ($row['facility_name'] ?? ''),
            ];
        }
        return $out;
    }

    /** @return list<array<string, mixed>> */
    private function immunizations(string $puuid): array
    {
        $result = (new ImmunizationService())->getAll([], true, $puuid);
        $out = [];
        foreach ($result->getData() as $row) {
            $out[] = [
                'source_id' => 'immunization:' . (int) $row['id'],
                'uuid' => (string) ($row['uuid'] ?? ''),
                'date' => self::date($row['administered_date'] ?? null),
                'cvx' => (string) ($row['cvx_code'] ?? ''),
                'name' => (string) ($row['cvx_code_text'] ?? ''),
            ];
        }
        return $out;
    }

    /** @return list<array<string, mixed>> */
    private function vitals(string $puuid): array
    {
        $result = (new VitalsService())->search([
            'puuid' => new TokenSearchField('puuid', [$puuid], true),
        ]);
        $out = [];
        foreach ($result->getData() as $row) {
            $out[] = [
                'source_id' => 'vitals:' . (int) $row['id'],
                'uuid' => (string) ($row['uuid'] ?? ''),
                'date' => self::date($row['date'] ?? null),
                'bps' => self::str($row['bps'] ?? null),
                'bpd' => self::str($row['bpd'] ?? null),
                'pulse' => self::str($row['pulse'] ?? null),
                'height' => self::str($row['height'] ?? null),
                'weight' => self::str($row['weight'] ?? null),
                'spo2' => self::str($row['oxygen_saturation'] ?? null),
                'bmi' => self::str($row['BMI'] ?? null),
                'temperature' => self::str($row['temperature'] ?? null),
            ];
        }
        return $out;
    }

    private static function date(mixed $value): ?string
    {
        if (!is_scalar($value)) {
            return null;
        }
        $text = substr((string) $value, 0, 10);
        return ($text === '' || str_starts_with($text, '0000-00-00')) ? null : $text;
    }

    private static function str(mixed $value): ?string
    {
        if (!is_scalar($value)) {
            return null;
        }
        $text = trim((string) $value);
        return $text === '' ? null : $text;
    }

    private static function age(mixed $dob): ?int
    {
        $date = self::date($dob);
        if ($date === null) {
            return null;
        }
        $birth = \DateTimeImmutable::createFromFormat('Y-m-d', $date);
        return $birth === false ? null : $birth->diff(new \DateTimeImmutable('today'))->y;
    }
}
