<?php

/**
 * The patient a link from the new dashboard is for, checked against the open chart (ADR 0006).
 *
 * The new dashboard has no PHP session; its patient comes from the SMART launch as a FHIR id,
 * so its Co-Pilot and Demo Data links carry `?patient=<uuid>`. These pages read the patient from
 * the session, which can hold a different chart. A link is accepted only when it names the
 * session patient; every other case is a refusal, decided here before anything patient-specific
 * is read or rendered. With no `patient` parameter the pages behave as they always have.
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

final readonly class LinkedPatient
{
    private const UUID_PATTERN = '/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/';

    private function __construct(
        public LinkState $state,
        /** The linked patient's pid; set for Matches and Mismatch only. */
        public ?int $linkedPid,
        /** The normalised (lower-case) uuid; set when it was well formed. */
        public ?string $uuid,
    ) {
    }

    /**
     * @param string $queryString the raw query string, so a repeated `patient` key is seen
     *                            (PHP keeps only the last one in $_GET)
     * @param callable(string): int $resolve returns the pid for a lower-case uuid, 0 when none
     */
    public static function fromQuery(string $queryString, int $sessionPid, callable $resolve): self
    {
        $values = [];
        foreach (explode('&', $queryString) as $pair) {
            if ($pair === '') {
                continue;
            }
            [$key, $value] = array_pad(explode('=', $pair, 2), 2, '');
            if (urldecode($key) === 'patient') {
                $values[] = urldecode($value);
            }
        }
        if ($values === []) {
            return new self(LinkState::NoLink, null, null);
        }
        if (count($values) > 1) {
            return new self(LinkState::Malformed, null, null);
        }
        $uuid = strtolower(trim($values[0]));
        if (preg_match(self::UUID_PATTERN, $uuid) !== 1) {
            return new self(LinkState::Malformed, null, null);
        }
        $linkedPid = $resolve($uuid);
        if ($linkedPid <= 0) {
            return new self(LinkState::Unknown, null, $uuid);
        }
        return new self($linkedPid === $sessionPid ? LinkState::Matches : LinkState::Mismatch, $linkedPid, $uuid);
    }

    /** Resolves a patient uuid to its pid through the uuid column, 0 when there is none. */
    public static function resolveFromDatabase(string $uuid): int
    {
        $bytes = UuidRegistry::uuidToBytes($uuid);
        $rows = QueryUtils::fetchRecords('SELECT pid FROM patient_data WHERE uuid = ?', [$bytes]);
        $pid = filter_var($rows[0]['pid'] ?? null, FILTER_VALIDATE_INT);
        return is_int($pid) ? $pid : 0;
    }

    /**
     * The token the refusal's "open this patient" form carries: bound to this session's key and
     * to the linked uuid, so it cannot be replayed from another session or for another patient.
     */
    public static function switchToken(string $sessionKey, string $uuid): string
    {
        return hash_hmac('sha256', 'copilot-link-switch|' . $uuid, $sessionKey);
    }

    public function acceptsSwitchToken(string $sessionKey, string $token): bool
    {
        // An empty key would make the token computable by anyone; no key, no switch.
        return $sessionKey !== '' && $this->uuid !== null && hash_equals(self::switchToken($sessionKey, $this->uuid), $token);
    }
}
