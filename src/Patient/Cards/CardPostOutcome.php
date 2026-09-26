<?php

/**
 * What a dashboard card did with the request's POST body (BUG-001, BUG-002, BUG-004).
 *
 * The page asks each writing card to handle its form before anything is rendered; a card no
 * longer writes while its template variables are built.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Patient\Cards;

enum CardPostOutcome
{
    /** The request carries no form for this card. */
    case NotSubmitted;
    /** The form was for this card, and the user may not write it: nothing was changed. */
    case Denied;
    /** The form was handled. */
    case Handled;
}
