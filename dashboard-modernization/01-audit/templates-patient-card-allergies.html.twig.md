# templates/patient/card/allergies.html.twig

**Role:** the Allergies card body.
**Size:** 52 lines. **Reached from:** demographics.php L1134.

## Purpose and behaviour

Lists active allergies (already filtered by the page). Empty state: "No Known Allergies" when the
allergy list has been touched (`listTouched`, from `getListTouch`), otherwise "Nothing Recorded".
Each row shows the title and, in parentheses, the severity looked up from `severity_ccda`; rows
with severity `severe`, `life_threatening_severity` or `fatal` get a warning background and bold
text. The row tooltip adds the reaction title.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Title, severity and reaction are escaped with `|text`/`|attr`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-AL-01 | Medium | L7-9 vs L39-49 | **Severe allergies are not pinned to the top**, although the header comment says they always are. The loop keeps the page's order. With the list's max-height rule commented out (demographics.php L983-986) nothing scrolls away today, but the documented clinical-safety behaviour is not there. |
| TPL-AL-02 | Low | L45 | **Empty severity renders as "()"** when an allergy has no severity recorded. |

## What the port keeps

**Required by the brief.** Parity rules for the port:
- rows = active allergies; title; severity in parentheses; reaction in the tooltip or a second line
- highlight severe / life-threatening / fatal, **and pin them to the top** (the documented rule)
- empty states "No Known Allergies" vs "Nothing Recorded" (see the spec for how FHIR represents the difference)
