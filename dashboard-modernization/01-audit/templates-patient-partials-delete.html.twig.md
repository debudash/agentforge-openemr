# templates/patient/partials/delete.html.twig

**Role:** the Delete Patient button.
**Size:** 15 lines. **Reached from:** demographics.php L2047.

## Purpose and behaviour

For a super-admin when patient deletion is allowed, a link to `deleter.php?patient=…&csrf_token_form=…`
opened in a dialog.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-DL-01 | Low | L12 | **CSRF token in a URL.** |
| TPL-DL-02 | Low | L1-3 | **Header comment says "Patient Portal card".** |

## What the port keeps

Nothing (the port is read-only).
