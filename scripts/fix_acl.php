<?php

/**
 * Grant the Physicians ACL group to doctor1 and doctor2.
 *
 * Calls the same AclExtended::setUserAro() the user-admin UI calls, so the gacl
 * ARO objects and group mappings are created exactly as the app would.
 * setUserAro() matches on the group TITLE ("Physicians"), not the value ("doc"),
 * and the first argument must be an array.
 *
 * Only needed when create_doctors.py reported HTTP 500 (the user row is created,
 * but the ACL step fails), or to change a user's group later.
 *
 * Run inside the openemr container as the web user, never as root — the flex
 * image's RootCliGuard rejects root CLI runs:
 *
 *   local:   docker compose exec -T openemr su -s /bin/sh apache -c \
 *              "php /var/www/localhost/htdocs/openemr/tmp/fix_acl.php"
 *   railway: base64 the file in, then `php /tmp/fix_acl.php` (see scripts/README.md)
 */

$_GET['site'] = 'default';
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['REQUEST_URI'] = '/cli';
$_SERVER['SCRIPT_NAME'] = '/cli';
$ignoreAuth = true;
$sessionAllowWrite = true;

require_once '/var/www/localhost/htdocs/openemr/interface/globals.php';

$doctors = [
    ['doctor1', 'Dana', '', 'Reyes'],
    ['doctor2', 'Samir', '', 'Okafor'],
];

foreach ($doctors as [$username, $first, $middle, $last]) {
    \OpenEMR\Common\Acl\AclExtended::setUserAro(['Physicians'], $username, $first, $middle, $last);
    $groups = \OpenEMR\Common\Acl\AclExtended::aclGetGroupTitles($username);
    echo $username . ' -> ' . (empty($groups) ? 'NO GROUPS' : implode(',', (array)$groups)) . PHP_EOL;
}
