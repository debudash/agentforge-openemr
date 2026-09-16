<?php

/**
 * Thrown when a read is attempted for a patient outside the signed-in provider's panel.
 * Carries only the pid, never whether that patient exists.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

final class ScopeDeniedException extends \RuntimeException
{
    public function __construct(public readonly int $pid)
    {
        parent::__construct('patient is not on the signed-in provider\'s rounding list');
    }
}
