# templates/patient/card/billing.html.twig

**Role:** the Billing card body.
**Size:** 60 lines. **Reached from:** BillingViewCard.

## Purpose and behaviour

Rows for patient, insurance and total balance, unallocated pre-payment and collections (when
positive), the billing note, and the primary insurer with copay and effective dates.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. All values escaped. Shown without a financial permission (BVC-01).

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-BL-01 | Low | L21, L28 | **Stray `</font>` closing tags** with no opening tag. |

## What the port keeps

Outside the brief.
