<?php

/**
 * Clinical Co-Pilot Agent module information.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

return [
    'name' => 'Clinical Co-Pilot Agent',
    'description' => 'Adds a CopilotAgent tab that hosts the clinical co-pilot for the hospitalist workflow defined in USER.md.',
    'version' => '0.1.0',
    'author' => 'Debu Dash',
    'license' => 'GPL-3.0',
    'acl_category' => 'patients',
    'acl_section' => 'demo',

    'require' => [
        'openemr' => '>=7.0.0',
    ],

    'menu' => [
        [
            'label' => 'CopilotAgent',
            'menu_id' => 'cpa0',
            'acl' => ['patients', 'demo'],
            'url' => '/interface/modules/custom_modules/oe-module-copilot-agent/public/index.php',
        ],
    ],
];
