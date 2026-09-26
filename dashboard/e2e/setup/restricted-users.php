<?php

/**
 * ADR 0005: restricted users for reproducing the legacy dashboard's Critical and High findings.
 * LOCAL DEV STACK ONLY. Never run this against Railway or any system with real data.
 *
 *   create:  docker compose exec -T openemr su -s /bin/sh apache -c \
 *              "php /var/www/localhost/htdocs/openemr/dashboard/e2e/setup/restricted-users.php create"
 *   remove:  ... restricted-users.php remove
 *
 * `create` prints {"username": "password", ...} on the last line; the caller stores it in the
 * gitignored dashboard/e2e/.auth/restricted-users.json. Each user gets one ACL group with exactly
 * the view permissions a reproduction needs:
 *
 *   dash-demoview   Dashboard Demographics View   patients|demo view only (no write, no med,
 *                                                 no lab, no disclosure): BUG-001, 002, 005, 006
 *   dash-nodemo     Dashboard No Demographics     patients|appt view only (no demo):  BUG-003, 008
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

$_GET['site'] = 'default';
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['REQUEST_URI'] = '/cli';
$_SERVER['SCRIPT_NAME'] = '/cli';
$ignoreAuth = true;
$sessionAllowWrite = true;

require_once '/var/www/localhost/htdocs/openemr/interface/globals.php';

use OpenEMR\Common\Acl\AclExtended;
use OpenEMR\Common\Auth\AuthHash;
use OpenEMR\Common\Database\QueryUtils;

$users = [
    'dash-demoview' => ['group' => 'Dashboard Demographics View', 'name' => 'dash_demoview', 'acos' => [['patients', 'Patients', 'demo', 'Demographics']]],
    'dash-nodemo' => ['group' => 'Dashboard No Demographics', 'name' => 'dash_nodemo', 'acos' => [['patients', 'Patients', 'appt', 'Appointments']]],
];

$mode = $argv[1] ?? '';
if ($mode === 'remove') {
    foreach ($users as $username => $spec) {
        $row = QueryUtils::fetchRecords('SELECT id FROM users WHERE username = ?', [$username]);
        if ($row !== []) {
            AclExtended::setUserAro([], $username, '', '', '');
            QueryUtils::sqlStatementThrowException('DELETE FROM users_secure WHERE username = ?', [$username]);
            QueryUtils::sqlStatementThrowException('DELETE FROM users WHERE username = ?', [$username]);
            QueryUtils::sqlStatementThrowException('DELETE FROM `groups` WHERE user = ?', [$username]);
        }
        ob_start();
        $ids = AclExtended::getAclIdNumber($spec['group'], 'view');
        if ($ids !== []) {
            AclExtended::aclRemove($spec['group'], 'view');
        }
        ob_end_clean();
        echo "removed {$username}" . PHP_EOL;
    }
    exit(0);
}
if ($mode !== 'create') {
    fwrite(STDERR, "usage: restricted-users.php create|remove\n");
    exit(2);
}

$passwords = [];
foreach ($users as $username => $spec) {
    ob_start(); // AclExtended echoes HTML progress messages
    $aclIds = AclExtended::getAclIdNumber($spec['group'], 'view');
    if ($aclIds === []) {
        $aclIds = AclExtended::addNewACL($spec['group'], $spec['name'], 'view', 'ADR 0005 local test group');
    }
    foreach ($spec['acos'] as [$section, $sectionTitle, $object, $objectTitle]) {
        AclExtended::updateAcl($aclIds, $spec['group'], $section, $sectionTitle, $object, $objectTitle, 'view');
    }
    ob_end_clean();

    $password = 'Dash-' . bin2hex(random_bytes(12));
    $hashInput = $password; // passwordHash() takes its argument by reference
    $hash = (new AuthHash())->passwordHash($hashInput);
    $existing = QueryUtils::fetchRecords('SELECT id FROM users WHERE username = ?', [$username]);
    if ($existing === []) {
        $id = QueryUtils::sqlInsert(
            "INSERT INTO users (username, password, authorized, active, fname, lname, facility_id, see_auth, calendar, main_menu_role, patient_menu_role)"
            . " VALUES (?, 'NoLongerUsed', 0, 1, 'Test', ?, 3, 1, 0, 'standard', 'standard')",
            [$username, $username]
        );
        QueryUtils::sqlStatementThrowException(
            'INSERT INTO users_secure (id, username, password, last_update_password) VALUES (?, ?, ?, NOW())',
            [$id, $username, $hash]
        );
    } else {
        QueryUtils::sqlStatementThrowException('UPDATE users_secure SET password = ?, last_update_password = NOW() WHERE username = ?', [$hash, $username]);
    }
    // Login also requires a row in the legacy `groups` table ("user not found in a group").
    if (QueryUtils::fetchRecords('SELECT id FROM `groups` WHERE user = ?', [$username]) === []) {
        QueryUtils::sqlStatementThrowException("INSERT INTO `groups` (name, user) VALUES ('Default', ?)", [$username]);
    }
    AclExtended::setUserAro([$spec['group']], $username, 'Test', '', $username);
    $passwords[$username] = $password;
    $titles = AclExtended::aclGetGroupTitles($username);
    fwrite(STDERR, $username . ' -> ' . (is_array($titles) ? implode(',', $titles) : 'NO GROUPS') . PHP_EOL);
}
echo json_encode($passwords, JSON_THROW_ON_ERROR) . PHP_EOL;
