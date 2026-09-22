<?php

/**
 * HTTP client for the agent service. Signs every request with the shared secret
 * (see copilot/copilot/service/auth.py for the scheme) and forwards the correlation ID.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

final class AgentClient
{
    public function __construct(private readonly Config $config)
    {
    }

    /**
     * @param array<string, mixed> $payload
     * @return array{status:int, json:array<string, mixed>|null}
     */
    /**
     * @param int|null $timeoutSeconds overrides the configured request timeout for one call. The
     *                                 supervisor may read several documents in one request (Week 2).
     */
    public function post(string $path, array $payload, string $correlationId, ?int $timeoutSeconds = null): array
    {
        $body = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($body === false) {
            throw new AgentUnavailableException('payload could not be encoded');
        }
        return $this->request('POST', $path, $body, $correlationId, $timeoutSeconds);
    }

    /** @return array{status:int, json:array<string, mixed>|null} */
    public function get(string $path, string $correlationId): array
    {
        return $this->request('GET', $path, '', $correlationId);
    }

    /** @return array{status:int, json:array<string, mixed>|null} */
    private function request(string $method, string $path, string $body, string $correlationId, ?int $timeoutSeconds = null): array
    {
        $timestamp = (string) time();
        $signature = hash_hmac('sha256', $timestamp . '.' . $method . '.' . $path . '.' . $body, $this->config->sharedSecret);

        $curl = curl_init($this->config->agentUrl . $path);
        if ($curl === false) {
            throw new AgentUnavailableException('curl init failed');
        }
        curl_setopt_array($curl, [
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_TIMEOUT => $timeoutSeconds ?? $this->config->requestTimeoutSeconds,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'X-Copilot-Timestamp: ' . $timestamp,
                'X-Copilot-Signature: ' . $signature,
                'X-Correlation-Id: ' . $correlationId,
            ],
            CURLOPT_POSTFIELDS => $method === 'POST' ? $body : null,
        ]);
        $response = curl_exec($curl);
        $status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
        $error = curl_error($curl);
        curl_close($curl);

        if (!is_string($response)) {
            throw new AgentUnavailableException('agent service unreachable: ' . $error);
        }
        $json = json_decode($response, true);
        return ['status' => $status, 'json' => is_array($json) ? $json : null];
    }
}
