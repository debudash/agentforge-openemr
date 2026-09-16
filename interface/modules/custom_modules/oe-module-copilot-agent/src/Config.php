<?php

/**
 * Module configuration: where the agent service is and the secret used to sign calls to it.
 *
 * Read from environment variables first (Railway sets them on the service), then from
 * sites/<site>/copilot-config.php (a plain PHP file returning an array; gitignored). The
 * file form exists so the local stack can be configured without recreating containers
 * and so Railway keeps the value on its persistent volume.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

final readonly class Config
{
    public function __construct(
        public string $agentUrl,
        public string $sharedSecret,
        public int $comparisonHours,
        public int $requestTimeoutSeconds,
        public int $labHistoryDays,
        public int $encounterHistoryDays,
    ) {
    }

    public static function load(string $siteDir): self
    {
        $file = [];
        $path = rtrim($siteDir, '/') . '/copilot-config.php';
        if (is_file($path)) {
            $loaded = include $path;
            if (is_array($loaded)) {
                $file = $loaded;
            }
        }
        return new self(
            agentUrl: rtrim(self::pick('COPILOT_AGENT_URL', $file, 'http://127.0.0.1:8600'), '/'),
            sharedSecret: self::pick('COPILOT_SHARED_SECRET', $file, ''),
            comparisonHours: (int) self::pick('COPILOT_COMPARISON_HOURS', $file, '24'),
            requestTimeoutSeconds: (int) self::pick('COPILOT_REQUEST_TIMEOUT_S', $file, '75'),
            labHistoryDays: (int) self::pick('COPILOT_LAB_HISTORY_DAYS', $file, '1095'),
            encounterHistoryDays: (int) self::pick('COPILOT_ENCOUNTER_HISTORY_DAYS', $file, '1825'),
        );
    }

    public function isConfigured(): bool
    {
        return $this->agentUrl !== '' && $this->sharedSecret !== '';
    }

    /**
     * @param array<string, mixed> $file
     */
    private static function pick(string $key, array $file, string $default): string
    {
        $env = getenv($key);
        if (is_string($env) && $env !== '') {
            return $env;
        }
        $value = $file[$key] ?? null;
        return is_scalar($value) && (string) $value !== '' ? (string) $value : $default;
    }
}
