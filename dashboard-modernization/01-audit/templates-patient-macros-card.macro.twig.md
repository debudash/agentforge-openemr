# templates/patient/macros/card.macro.twig

**Role:** macro `injectedContent(content)` that includes each module-supplied template in a list.
**Size:** 20 lines. **Reached from:** `portal.html.twig` only, whose result is discarded.

## Purpose and behaviour

For each item implementing the render interface, `include(row.getTemplateFile, row.getVariables)`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-MC-01 | Medium | whole file | **The only renderer for module card injections is never used with output** (see TPL-CB-04). |

## What the port keeps

The extension idea (modules add content to a card) is worth keeping as a slot in the new component tree.
