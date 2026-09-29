# templates/patient/card/preference_card_inline.html.twig

**Role:** the shared view-and-edit body for both preference cards.
**Size:** 422 lines. **Reached from:** TreatmentPreferenceViewCard, CareExperiencePreferenceViewCard.

## Purpose and behaviour

Like the care team template it opens its own `<html><head>` and calls `setupHeader()` (L24-28). The
view is a table of preferences: date, preference (LOINC display) with note, the patient's choice
(coded display, free text or yes/no) and status, with edit and delete buttons when `auth and
can_write` (always true, TPC-01). Delete is a per-row form (L121-129). The edit form (L144-236)
has a LOINC select, date, status, answer type radios, coded answers loaded by AJAX from
`library/ajax/get_preference_answers.php` (L302), free text, yes/no and note. The script (L240-419)
binds **document-level** delegated handlers for edit, cancel, answer type and row edit.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-PR-01 | High | L76 | **Stored XSS through `observation_code_text`.** `{{ pref.observation_code_text ?? pref.code_display\|default('')\|text }}`: Twig applies filters before `??`, so when `observation_code_text` is set it is printed **unescaped**. That field is a hidden input the client fills and the server stores as given (TreatmentPreferenceViewCard L195). |
| TPL-PR-02 | High | L117 | **Attribute injection through `data-pref='{{ pref\|json_encode }}'`.** JSON does not escape single quotes, so a note containing `'` closes the attribute and can add an event handler. |
| TPL-PR-03 | Medium | L24-28 | **Nested `<html><head>` and `setupHeader()` mid-body** (as TPL-CT-02). |
| TPL-PR-04 | Low | L346-379 | **Delegated handlers are bound once per card instance**; with both preference cards on the page every click runs two sets of handlers. |
| TPL-PR-05 | Low | L13-21 | **Blocks `card_title` and `card_header_actions` override nothing**; the base template has no such blocks. |
| TPL-PR-06 | Low | L74 | **`\|date` on an unparsable value throws**, failing the whole page render. |

## What the port keeps

Outside the brief.
