<?php

/**
 * Stored values in the patient dashboard's preference cards must reach the page escaped
 * (BUG-009 and BUG-011 in the dashboard modernization catalog). BUG-010, the care team note,
 * is built into the DOM by the browser, so its test is a browser test
 * (dashboard/e2e/legacy/legacy-security.spec.ts).
 *
 * Twig autoescaping is off application-wide (TwigContainer), so each sink has to escape on its
 * own. These tests render the real template with hostile stored values and assert that no
 * value can end an attribute or open a tag.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Debu Dash
 * @copyright Copyright (c) 2026 Debu Dash
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Patient\Cards;

use OpenEMR\Common\Twig\TwigContainer;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\Attributes\Test;
use PHPUnit\Framework\TestCase;
use Twig\Environment;
use Twig\TwigFunction;

#[Group('isolated')]
#[Group('twig')]
final class PatientCardTemplateEscapingTest extends TestCase
{
    private const TAG = '<img src=x onerror=alert(1)>';
    private const ATTRIBUTE_BREAK = "x' onmouseover='alert(1)";

    private static ?Environment $twig = null;

    protected function setUp(): void
    {
        $GLOBALS['fileroot'] ??= dirname(__DIR__, 5);
        $GLOBALS['date_display_format'] ??= 0;
        $GLOBALS['disable_translation'] = true;
    }

    #[Test]
    public function observationCodeTextIsEscapedInThePreferenceList(): void
    {
        $html = $this->renderPreferenceCard(['observation_code_text' => self::TAG]);

        self::assertStringNotContainsString(self::TAG, $html, 'BUG-011: observation_code_text printed unescaped');
        self::assertStringContainsString('&lt;img src=x onerror=alert(1)&gt;', $html);
    }

    #[Test]
    public function codeDisplayIsTheFallbackWhenObservationCodeTextIsEmpty(): void
    {
        $html = $this->renderPreferenceCard(['observation_code_text' => null, 'code_display' => 'Fallback & display']);

        self::assertStringContainsString('<strong>Fallback &amp; display</strong>', $html);
    }

    #[Test]
    public function aQuoteInAStoredValueCannotEndTheEditButtonsDataAttribute(): void
    {
        $html = $this->renderPreferenceCard(['note' => self::ATTRIBUTE_BREAK, 'value_text' => self::ATTRIBUTE_BREAK]);

        // The edit button's opening tag must carry no attribute the stored value smuggled in.
        self::assertSame(1, preg_match('/<button[^>]*js-edit-row[^>]*>/', $html, $button));
        self::assertStringNotContainsString("onmouseover='", $button[0], 'BUG-009: a quote in the JSON ended the attribute');
        self::assertMatchesRegularExpression('/data-pref="[^"]*"/', $button[0], 'data-pref must be a double-quoted, attribute-escaped value');

        // The attribute still carries the whole row for the edit form.
        self::assertSame(1, preg_match('/data-pref="([^"]*)"/', $html, $m));
        $decoded = json_decode(html_entity_decode($m[1], ENT_QUOTES | ENT_HTML5), true);
        self::assertIsArray($decoded);
        self::assertSame(self::ATTRIBUTE_BREAK, $decoded['note']);
    }

    /**
     * @param array<string, mixed> $overrides
     */
    private function renderPreferenceCard(array $overrides): string
    {
        $pref = array_merge([
            'id' => 7,
            'patient_id' => 3,
            'effective_datetime' => '2026-09-01 10:00:00',
            'recorded_date' => '2026-09-01 10:00:00',
            'updated_at' => null,
            'observation_code' => '95541-9',
            'observation_code_text' => 'Care experience preference',
            'observation_code_system' => 'http://loinc.org',
            'code_display' => 'Care experience preference',
            'value_type' => 'text',
            'value_code' => null,
            'value_display' => null,
            'value_code_system' => null,
            'value_boolean' => null,
            'value_text' => 'plain',
            'status' => 'final',
            'note' => '',
            'user_id' => 1,
            'user_display' => 'Test User',
        ], $overrides);

        return self::twig()->render('patient/card/preference_card_inline.html.twig', [
            'title' => 'Care Experience Preferences',
            'id' => 'carepref_ps_expand',
            'type' => 'care_experience',
            'pid' => 3,
            'auth' => true,
            'can_write' => true,
            'webroot' => '',
            'csrf_token' => 'token',
            'preferences' => [$pref],
            'loinc_codes' => [],
            'current_datetime' => '2026-09-25T10:00',
            'message' => null,
            'initiallyCollapsed' => false,
            'forceAlwaysOpen' => true,
        ]);
    }

    private static function twig(): Environment
    {
        if (self::$twig !== null) {
            return self::$twig;
        }
        $twig = (new TwigContainer())->getTwig();
        // The real functions need the kernel and a session; stubbed as TwigTemplateRenderTest does.
        $twig->addFunction(new TwigFunction('setupHeader', fn(): string => '<!-- setupHeader stub -->', ['is_safe' => ['html']]));
        $twig->addFunction(new TwigFunction('csrfTokenRaw', fn(): string => 'test-csrf-token'));
        self::$twig = $twig;
        return $twig;
    }
}
