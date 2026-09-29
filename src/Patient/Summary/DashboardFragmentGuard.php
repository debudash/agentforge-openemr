<?php

/**
 * Authorization for the patient dashboard's AJAX fragments (BUG-006).
 *
 * The dashboard decides which cards to draw, and the fragments behind those cards used to trust
 * that decision: any signed-in user with a CSRF token could post to them and get the session
 * patient's vitals, labs, disclosures or any LBF form. Each fragment now repeats the checks the
 * page makes before it shows the card: patients/demo, the patient's squad, and the card's own ACL.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Patient\Summary;

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Database\QueryUtils;

final class DashboardFragmentGuard
{
    /**
     * @param mixed $sessionPid the session's pid as stored (narrowed here, never cast)
     * @param list<array{string, string}> $cardAcos the ACOs the page requires to show the card
     */
    public static function allows(mixed $sessionPid, array $cardAcos): bool
    {
        $pid = filter_var($sessionPid, FILTER_VALIDATE_INT);
        if (!is_int($pid) || $pid <= 0 || !AclMain::aclCheckCore('patients', 'demo')) {
            return false;
        }
        $squad = QueryUtils::fetchSingleValue('SELECT squad FROM patient_data WHERE pid = ?', 'squad', [$pid]);
        if (is_string($squad) && $squad !== '' && !AclMain::aclCheckCore('squads', $squad)) {
            return false;
        }
        foreach ($cardAcos as [$section, $value]) {
            if (!AclMain::aclCheckCore($section, $value)) {
                return false;
            }
        }
        return true;
    }

    /**
     * The ACO an LBF card requires, or null when `$formId` is not an active LBF layout (the page
     * only ever loads LBF cards for those, so anything else is not a dashboard card).
     *
     * @return list<array{string, string}>|null
     */
    public static function lbfCardAcos(string $formId): ?array
    {
        if (preg_match('/^LBF[A-Za-z0-9_]{1,28}$/', $formId) !== 1) {
            return null;
        }
        $rows = QueryUtils::fetchRecords(
            "SELECT grp_aco_spec FROM layout_group_properties WHERE grp_form_id = ? AND grp_group_id = '' AND grp_activity = 1",
            [$formId]
        );
        if ($rows === []) {
            return null;
        }
        $spec = $rows[0]['grp_aco_spec'] ?? '';
        if (!is_string($spec) || $spec === '') {
            return [];
        }
        $parts = explode('|', $spec);
        return count($parts) >= 2 ? [[$parts[0], $parts[1]]] : [];
    }

    public static function deny(): never
    {
        http_response_code(403);
        echo text(xl('Not authorized'));
        exit;
    }
}
