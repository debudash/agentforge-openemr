<?php

/**
 * Which patient the clinician currently has open, across OpenEMR versions.
 *
 * `PatientSessionUtil::getPid()` is the right accessor and is what this module developed
 * against, but it does not exist in OpenEMR 8.0.0 -- that release ships `setPid()` alone. Calling
 * it there is a fatal `Call to undefined method`, which is a blank 500 to the clinician: the
 * Co-Pilot and Demo Data tabs opened and rendered nothing on the deployed 8.0.0 instance while
 * working locally against 8.1-dev.
 *
 * So ask for the accessor, and fall back to where 8.0.0's `setPid()` actually puts the value: the
 * session wrapper, which `SessionUtil::setUnsetSession()` writes through. The raw `$_SESSION`
 * superglobal is last and least trusted -- on 8.1-dev it reads 0 on a perfectly good session,
 * which is the bug that put `PatientSessionUtil` here in the first place.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

use OpenEMR\Common\Session\PatientSessionUtil;
use OpenEMR\Common\Session\SessionWrapperFactory;
use Throwable;

final class ActivePatient
{
    /** The open patient, or 0 when no chart is open. Never throws: no chart is a valid answer. */
    public static function pid(): int
    {
        if (method_exists(PatientSessionUtil::class, 'getPid')) {
            return (int) PatientSessionUtil::getPid();
        }

        // OpenEMR 8.0.0: setPid() writes 'pid' through the session wrapper.
        if (class_exists(SessionWrapperFactory::class)) {
            try {
                $pid = SessionWrapperFactory::getInstance()->getWrapper()->get('pid');
                if ($pid !== null) {
                    return (int) $pid;
                }
            } catch (Throwable) {
                // Fall through: an unavailable wrapper is not a reason to fail the page.
            }
        }

        return (int) ($_SESSION['pid'] ?? 0);
    }
}
