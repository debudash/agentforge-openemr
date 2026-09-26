# templates/patient/card/insurance.html.twig

**Role:** the Insurance card body: tabs per coverage type, paged policy history, eligibility.
**Size:** 196 lines. **Reached from:** InsuranceViewCard.

## Purpose and behaviour

Nav tabs for primary (always) and any secondary/tertiary with data, plus Eligibility. Each tab pages
through the current and historical policies: insurer name and address; subscriber name,
relationship, address, **SSN**, DOB, phone; subscriber employer; plan name, policy and group
numbers, copay, accepts assignment, Medicare secondary type. The Eligibility tab shows stored
results and, when enabled, a form that POSTs `status_update=true` to `./demographics.php`. Inline
script handles pagination.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Fields `|text`-escaped. The eligibility form has **no CSRF token**.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-IN-01 | Medium | L61-64 | **Full subscriber SSN displayed** (IVC-02). |
| TPL-IN-02 | Medium | L129-134 | **Eligibility form without a CSRF token** triggers an outbound X12 270 (IVC-01). |
| TPL-IN-03 | Low | L16-20 | **`<li>` opened and never closed** inside the loop. |
| TPL-IN-04 | Low | L28 | **Generic element ids** `primary`, `secondary`, `tertiary`, `eligibility` can collide with other elements on the page. |
| TPL-IN-05 | Low | L188-190 | **Click handler on the `<li>`** reads `dataset` from `e.target`; clicking the padding (not the link) throws a TypeError. |

## What the port keeps

Outside the brief.
