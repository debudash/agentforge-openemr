# templates/patient/card/adv_dir.html.twig

**Role:** the Advance Directives card body.
**Size:** 20 lines. **Reached from:** demographics.php L1721.

## Purpose and behaviour

One link per advance-directive category that has a document (newest per category), with the
document date; "None" otherwise.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Links escaped with `attr`/`attr_url`. The card has no ACL check on the page.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-AD-01 | Low | L14 | **Leftover `{{ a }}` after the loop** (prints nothing today because the loop variable is out of scope). |
| TPL-AD-02 | Medium | demographics.php L1663-1722 | **No authorization for the card** (documents are listed to anyone who can open the dashboard). |

## What the port keeps

Outside the brief.
