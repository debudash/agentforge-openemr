# src/Patient/Cards/InsuranceViewCard.php

**Role:** the Insurance card: primary/secondary/tertiary policies with history, and eligibility.
**Size:** 195 lines. **Reached from:** `addCard(new InsuranceViewCard($pid, …))` at demographics.php L1347.

## Purpose and lifecycle

On render it loads the policies organised by type (L68-90), enriches each with the insurer's name
and address and the subscriber's full name (L91-133), and produces the eligibility output
(L134-163): if eligibility requests are enabled **and the POST body has `status_update=true`**, it
calls `EDI270::requestEligibleTransaction($pid)` — an outbound X12 270 request to the
clearinghouse — and shows the result; otherwise it shows the stored eligibility information.

## Controls

- **Authorization:** ACL `patients/demo` (L29). Edit with write (L27).
- **CSRF:** **none** on the eligibility trigger. The template's form posts to `./demographics.php`
  with no token (insurance.html.twig L129-134), and this class does not check one.
- **Escaping:** template uses `|text`; `eligibility` HTML comes from EDI270 and is printed raw.

## Database touches

Reads `insurance_data`, `insurance_companies`, `addresses`, eligibility tables. The eligibility path
writes the request/response records.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| IVC-01 | Medium | L134-149 | **Cross-site request forgery on an outbound transaction.** A page on another site can make a logged-in user's browser POST `status_update=true` to the dashboard and trigger a payer eligibility request. |
| IVC-02 | Medium | insurance.html.twig L61-64 | **Full subscriber SSN displayed** to anyone with demographics read. Minimum-necessary would mask it. |
| IVC-03 | Low | L140 | **`$showEligibility` is set and never returned**; the page's auto-open of the eligibility tab (demographics.php L2068) can never fire. |
| IVC-04 | Low | L110 | **Unknown `policy_type` key** yields an undefined-index warning. |
| IVC-05 | Low | L62-67 | **Unused private method** `getInsuranceTypeArray()`; the page has its own copy (demographics.php L136). |

## What the port keeps

Outside the brief. FHIR `Coverage` exists if it is added later; it would not carry SSNs.
