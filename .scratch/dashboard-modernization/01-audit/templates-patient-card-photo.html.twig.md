# templates/patient/card/photo.html.twig

**Role:** the ID Card / Photos card body.
**Size:** 18 lines. **Reached from:** demographics.php L1659.

## Purpose and behaviour

Calls the Twig function `imageWidget(docId, category)` for each photo and each ID-card document.
`imageWidget` calls `image_widget()`, which is declared inside demographics.php (TwigExtension.php
L185-189).

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Escaping happens inside `image_widget()`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-PH-01 | Low | L4 | **Photos gated on the wrong setting**: the photo loop runs only when `patientIDCategoryID` (the ID-card category) is set, not the photo category. |
| TPL-PH-02 | Medium | TwigExtension.php L185 | **Global Twig function depends on a page-local PHP function**; using it anywhere else is a fatal error. |

## What the port keeps

The identity bar's photo (a different code path). Otherwise outside the brief.
