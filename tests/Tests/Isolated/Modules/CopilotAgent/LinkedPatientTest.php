<?php

/**
 * How a `?patient=<uuid>` link from the new dashboard is classified (ADR 0006). The page-level
 * refusal path is tested against the live stack in usecases/test_uc_dashboard_links.py; this
 * covers the parsing rules without a database.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\CopilotAgent;

use Composer\Autoload\ClassLoader;
use OpenEMR\Modules\CopilotAgent\LinkedPatient;
use OpenEMR\Modules\CopilotAgent\LinkState;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Test;
use PHPUnit\Framework\TestCase;

final class LinkedPatientTest extends TestCase
{
    private const UUID = 'a2bf78bb-8052-4600-a47f-567135c1f296';

    /**
     * @codeCoverageIgnore Fixture wiring; runs before coverage attribution.
     */
    public static function setUpBeforeClass(): void
    {
        // The module registers its namespace from its bootstrap at runtime; there is none here.
        $loaders = ClassLoader::getRegisteredLoaders();
        $loader = reset($loaders);
        if (!$loader instanceof ClassLoader) {
            self::fail('Composer ClassLoader not available to register the module autoload prefix.');
        }
        $loader->addPsr4('OpenEMR\\Modules\\CopilotAgent\\', dirname(__DIR__, 5) . '/interface/modules/custom_modules/oe-module-copilot-agent/src/');
    }

    /** @return callable(string): int */
    private static function resolver(): callable
    {
        return static fn(string $uuid): int => $uuid === self::UUID ? 3 : 0;
    }

    #[Test]
    public function noPatientParameterLeavesThePageAsItWas(): void
    {
        self::assertSame(LinkState::NoLink, LinkedPatient::fromQuery('site=default', 3, self::resolver())->state);
        self::assertSame(LinkState::NoLink, LinkedPatient::fromQuery('', 3, self::resolver())->state);
    }

    #[Test]
    public function theOpenChartsUuidMatchesInAnyCase(): void
    {
        $link = LinkedPatient::fromQuery('patient=' . strtoupper(self::UUID) . '&site=default', 3, self::resolver());
        self::assertSame(LinkState::Matches, $link->state);
        self::assertSame(self::UUID, $link->uuid);
    }

    #[Test]
    public function anotherPatientsUuidIsAMismatch(): void
    {
        $link = LinkedPatient::fromQuery('patient=' . self::UUID, 5, self::resolver());
        self::assertSame(LinkState::Mismatch, $link->state);
        self::assertSame(3, $link->linkedPid);
    }

    #[Test]
    public function noChartOpenIsAMismatchToo(): void
    {
        self::assertSame(LinkState::Mismatch, LinkedPatient::fromQuery('patient=' . self::UUID, 0, self::resolver())->state);
    }

    #[Test]
    public function aWellFormedUuidThatIsNoPatientIsUnknown(): void
    {
        $link = LinkedPatient::fromQuery('patient=00000000-0000-4000-8000-000000000000', 3, self::resolver());
        self::assertSame(LinkState::Unknown, $link->state);
        self::assertNull($link->linkedPid);
    }

    /**
     * @return array<string, array{string}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function malformedProvider(): array
    {
        return [
            'a pid' => ['patient=3'],
            'empty' => ['patient='],
            'not a uuid' => ['patient=not-a-uuid'],
            'sql' => ['patient=%27%20OR%20%271%27%3D%271'],
            'markup' => ['patient=%3Cscript%3E'],
            'trailing junk' => ['patient=' . self::UUID . 'x'],
            'repeated' => ['patient=' . self::UUID . '&patient=00000000-0000-4000-8000-000000000000'],
            'repeated, same value' => ['patient=' . self::UUID . '&patient=' . self::UUID],
        ];
    }

    #[Test]
    #[DataProvider('malformedProvider')]
    public function anythingElseIsMalformedAndNeverResolved(string $query): void
    {
        $resolved = false;
        $link = LinkedPatient::fromQuery($query, 3, static function (string $uuid) use (&$resolved): int {
            $resolved = true;
            return 3;
        });
        self::assertSame(LinkState::Malformed, $link->state);
        self::assertFalse($resolved, 'a malformed value must not reach the database');
    }

    #[Test]
    public function theSwitchTokenIsBoundToTheSessionAndThePatient(): void
    {
        $link = LinkedPatient::fromQuery('patient=' . self::UUID, 5, self::resolver());
        $token = LinkedPatient::switchToken('session-key', self::UUID);

        self::assertTrue($link->acceptsSwitchToken('session-key', $token));
        self::assertFalse($link->acceptsSwitchToken('another-session', $token));
        self::assertFalse($link->acceptsSwitchToken('session-key', LinkedPatient::switchToken('session-key', '00000000-0000-4000-8000-000000000000')));
        self::assertFalse($link->acceptsSwitchToken('', LinkedPatient::switchToken('', self::UUID)), 'no session key, no switch');
    }
}
