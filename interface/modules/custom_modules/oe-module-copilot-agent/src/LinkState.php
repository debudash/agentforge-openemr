<?php

/**
 * What a `?patient=<uuid>` link from the new dashboard amounts to (ADR 0006).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

enum LinkState
{
    /** No `patient` parameter: the page behaves as it always has. */
    case NoLink;
    /** The link names the patient the session has open. */
    case Matches;
    /** The link names another patient than the open chart. */
    case Mismatch;
    /** A well-formed uuid that is no patient. */
    case Unknown;
    /** Not a uuid, or the parameter was repeated. */
    case Malformed;
}
