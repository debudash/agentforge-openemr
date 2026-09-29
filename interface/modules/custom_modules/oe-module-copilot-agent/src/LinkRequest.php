<?php

/**
 * The parts of the request the dashboard-link gate reads, parsed once at the entry point.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

use Symfony\Component\HttpFoundation\Request;

final readonly class LinkRequest
{
    private function __construct(
        public string $queryString,
        public string $method,
        public string $switchToken,
        /** Path and query of this request, the target of the switch form and its redirect. */
        public string $selfUrl,
    ) {
    }

    public static function fromRequest(Request $request): self
    {
        $token = $request->request->get('cpa_switch_token');
        return new self(
            $request->server->getString('QUERY_STRING'),
            $request->getMethod(),
            is_string($token) ? $token : '',
            $request->getRequestUri(),
        );
    }
}
