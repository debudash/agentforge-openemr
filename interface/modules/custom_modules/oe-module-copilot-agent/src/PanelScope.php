<?php

/**
 * Who may use the co-pilot, and which patients they may see.
 *
 * OpenEMR's ACLs are role based and never restrict a user to "their" patients
 * (AUDIT.md S3, measured). This class is therefore the authorization boundary the
 * PRD requires (FR2, FR15): the signed-in user must be a provider in the Physicians
 * ACL group (the OpenEMR mapping of the PRD's "hospitalist"), and a patient is in
 * scope only when patient_data.providerID is that user. Every read in ChartReader
 * goes through assertInScope(); the agent service repeats the check on its side.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

use OpenEMR\Common\Acl\AclExtended;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Services\AppointmentService;
use OpenEMR\Services\Search\SearchModifier;
use OpenEMR\Services\Search\StringSearchField;
use OpenEMR\Services\UserService;

final class PanelScope
{
    /** The OpenEMR ACL group mapped to the PRD's hospitalist role (PRD "OpenEMR role mapping"). */
    public const HOSPITALIST_GROUP = 'Physicians';

    /** @var array<string, mixed> */
    private array $user;

    /** @var list<string> */
    private array $groups;

    /**
     * @param array<string, mixed> $user  the users row of the signed-in user
     * @param list<string> $groups        the user's gacl group titles
     */
    private function __construct(array $user, array $groups)
    {
        $this->user = $user;
        $this->groups = $groups;
    }

    public static function forCurrentUser(): self
    {
        $user = (new UserService())->getCurrentlyLoggedInUser();
        if (!is_array($user) || empty($user['id'])) {
            throw new \RuntimeException('no signed-in user');
        }
        $titles = AclExtended::aclGetGroupTitles((string) ($user['username'] ?? ''));
        return new self($user, is_array($titles) ? array_values(array_map('strval', $titles)) : []);
    }

    public function userId(): int
    {
        return (int) $this->user['id'];
    }

    public function username(): string
    {
        return (string) ($this->user['username'] ?? '');
    }

    public function displayName(): string
    {
        $name = trim(((string) ($this->user['fname'] ?? '')) . ' ' . ((string) ($this->user['lname'] ?? '')));
        return $name !== '' ? $name : $this->username();
    }

    /** @return list<string> */
    public function groups(): array
    {
        return $this->groups;
    }

    /**
     * FR15: hospitalist only. A provider (authorized=1) in the Physicians group. Administrators
     * and every other role are denied by default, even though they can open the tab.
     */
    public function isHospitalist(): array
    {
        if (!in_array(self::HOSPITALIST_GROUP, $this->groups, true)) {
            return [false, 'role not supported: the co-pilot is enabled for the Physicians group only'];
        }
        if ((int) ($this->user['authorized'] ?? 0) !== 1) {
            return [false, 'role not supported: the account is not a provider'];
        }
        return [true, 'hospitalist'];
    }

    /**
     * The rounding list: today's appointments booked for this provider, restricted to patients
     * whose assigned provider is this user. Both conditions must hold (appointment ⊂ panel).
     *
     * @return list<array{pid:int,eid:int,time:string,title:string,status:string}>
     */
    public function roundingList(string $date): array
    {
        $result = (new AppointmentService())->search([
            'pc_aid' => new StringSearchField('pc_aid', [(string) $this->userId()], SearchModifier::EXACT),
            'pc_eventDate' => new StringSearchField('pc_eventDate', [$date], SearchModifier::EXACT),
        ]);
        $rows = $result->getData();
        $list = [];
        $seen = [];
        foreach ($rows as $row) {
            $pid = (int) ($row['pc_pid'] ?? 0);
            if ($pid <= 0 || isset($seen[$pid]) || !$this->isInScope($pid)) {
                continue;
            }
            $seen[$pid] = true;
            $list[] = [
                'pid' => $pid,
                'eid' => (int) ($row['pc_eid'] ?? 0),
                'time' => substr((string) ($row['pc_startTime'] ?? ''), 0, 5),
                'title' => (string) ($row['pc_title'] ?? ''),
                'status' => (string) ($row['pc_apptstatus'] ?? ''),
            ];
        }
        usort($list, static fn(array $a, array $b): int => strcmp($a['time'], $b['time']));
        return $list;
    }

    /** Number of patients assigned to this provider (for the header, not for access). */
    public function panelSize(): int
    {
        $row = QueryUtils::fetchRecords('SELECT COUNT(*) AS n FROM patient_data WHERE providerID = ?', [$this->userId()]);
        return (int) ($row[0]['n'] ?? 0);
    }

    public function isInScope(int $pid): bool
    {
        $row = QueryUtils::fetchRecords('SELECT providerID FROM patient_data WHERE pid = ?', [$pid]);
        return !empty($row) && (int) ($row[0]['providerID'] ?? 0) === $this->userId();
    }

    /** Fail closed: any read of a patient outside the panel stops here (REQ-SCOPE-1). */
    public function assertInScope(int $pid): void
    {
        if (!$this->isInScope($pid)) {
            throw new ScopeDeniedException($pid);
        }
    }
}
