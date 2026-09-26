<?php

/**
 * The refusal path for dashboard links (ADR 0006, spec 12.1), shared by patient.php and demo.php.
 *
 * Runs after the page's own ACL check and before anything patient-specific. A link that does not
 * name the open chart is refused with a page that starts no co-pilot and shows no chart data; a
 * mismatch names both patients and offers to open the dashboard's patient here, which takes a
 * POST carrying a token bound to this session and that patient. The panel check still runs on
 * the page afterwards, so opening a patient never bypasses it.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\CopilotAgent;

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Logging\EventAuditLogger;
use OpenEMR\Common\Session\PatientSessionUtil;
use OpenEMR\Core\Header;
use OpenEMR\Core\OEGlobalsBag;
use OpenEMR\Events\PatientDemographics\ViewEvent;

final readonly class LinkGate
{
    public function __construct(
        private string $entry,
        private string $pageTitle,
        private string $username,
        private string $authGroup,
        private string $sessionKey,
    ) {
    }

    /**
     * Returns when the page may render as usual (no link, or a link to the open chart).
     * Otherwise it answers the request itself and exits.
     */
    public function enforce(LinkedPatient $link, int $sessionPid, LinkRequest $request): void
    {
        match ($link->state) {
            LinkState::NoLink, LinkState::Matches => null,
            LinkState::Malformed => $this->refuse(400, xl('This link does not name a patient. Open the Co-Pilot again from the dashboard.'), null),
            LinkState::Unknown => $this->refuse(404, xl('No patient matches this link.'), null),
            LinkState::Mismatch => $this->refuseMismatch($link, $sessionPid, $request),
        };
    }

    /**
     * The link names another patient than the open chart. A GET is refused, naming both and
     * offering to open the linked patient here; a POST carrying that offer's token switches.
     */
    private function refuseMismatch(LinkedPatient $link, int $sessionPid, LinkRequest $request): never
    {
        $linkedPid = $link->linkedPid;
        $uuid = $link->uuid;
        if ($linkedPid === null || $uuid === null) {
            throw new \LogicException('A mismatched link always carries the linked pid and uuid');
        }
        // The form posts back to, and the switch redirects to, this same page: a path on this
        // host, never anything a request could point elsewhere ("//host", "https:").
        $selfUrl = str_starts_with($request->selfUrl, '/') && !str_starts_with($request->selfUrl, '//') ? $request->selfUrl : '';

        // A patient this user may not open is neither named nor offered, and cannot be switched
        // to: the same checks demographics.php makes before it shows a chart.
        if (!$this->mayOpen($linkedPid)) {
            $this->audit('copilot-link-not-permitted', 'session_pid=' . $sessionPid, $linkedPid, false);
            $this->refuse(403, xl('This link is for a patient you cannot open.'), null);
        }

        if ($request->method === 'POST') {
            if (!$link->acceptsSwitchToken($this->sessionKey, $request->switchToken)) {
                $this->audit('copilot-link-switch-denied', 'bad token session_pid=' . $sessionPid, $linkedPid, false);
                $this->refuse(403, xl('This request could not be confirmed. Open the link again from the dashboard.'), null);
            }
            PatientSessionUtil::setPid($linkedPid);
            $this->audit('copilot-link-switch', 'session_pid=' . $sessionPid, $linkedPid, true);
            header('Location: ' . $selfUrl, true, 303);
            exit;
        }

        $this->audit('copilot-link-mismatch', 'session_pid=' . $sessionPid, $linkedPid, false);
        $linked = $this->patientName($linkedPid);
        $open = $sessionPid > 0 ? $this->patientName($sessionPid) : '';
        $message = $open !== ''
            ? sprintf(xl('The dashboard link is for %1$s, but %2$s is the chart open in OpenEMR. Nothing is shown for either until they match.'), $linked, $open)
            : sprintf(xl('The dashboard link is for %s, but no chart is open in OpenEMR.'), $linked);
        $this->refuse(409, $message, [
            'label' => sprintf(xl('Open %s here'), $linked),
            'token' => LinkedPatient::switchToken($this->sessionKey, $uuid),
            'action' => $selfUrl,
        ]);
    }

    private function mayOpen(int $pid): bool
    {
        if (!AclMain::aclCheckCore('patients', 'demo')) {
            return false;
        }
        $viewEvent = OEGlobalsBag::getInstance()->getKernel()->getEventDispatcher()->dispatch(new ViewEvent($pid), ViewEvent::EVENT_HANDLE);
        if (!$viewEvent->authorized()) {
            return false;
        }
        $squad = QueryUtils::fetchSingleValue('SELECT squad FROM patient_data WHERE pid = ?', 'squad', [$pid]);
        return !is_string($squad) || $squad === '' || AclMain::aclCheckCore('squads', $squad);
    }

    private function patientName(int $pid): string
    {
        $rows = QueryUtils::fetchRecords('SELECT fname, lname FROM patient_data WHERE pid = ?', [$pid]);
        $fname = $rows[0]['fname'] ?? '';
        $lname = $rows[0]['lname'] ?? '';
        return trim((is_string($fname) ? $fname : '') . ' ' . (is_string($lname) ? $lname : ''));
    }

    private function audit(string $event, string $detail, int $pid, bool $allowed): void
    {
        EventAuditLogger::getInstance()->newEvent($event, $this->username, $this->authGroup, $allowed ? 1 : 0, 'entry=' . $this->entry . ' ' . $detail, $pid);
    }

    /**
     * @param array{label: string, token: string, action: string}|null $offer
     */
    private function refuse(int $status, string $message, ?array $offer): never
    {
        http_response_code($status);
        header('Cache-Control: no-store');
        echo "<!DOCTYPE html>\n<html>\n<head>\n";
        Header::setupHeader();
        echo '<title>' . text($this->pageTitle) . "</title>\n</head>\n<body class=\"container py-3\">\n";
        echo '<h1 class="h4">' . text($this->pageTitle) . "</h1>\n";
        echo '<div id="cpa-link-refused" class="alert alert-warning" role="alert">' . text($message) . "</div>\n";
        if ($offer !== null) {
            echo '<form method="post" action="' . attr($offer['action']) . '">'
                . '<input type="hidden" name="cpa_switch_token" value="' . attr($offer['token']) . '">'
                . '<button type="submit" class="btn btn-primary">' . text($offer['label']) . '</button>'
                . "</form>\n";
        }
        echo "</body>\n</html>\n";
        exit;
    }
}
