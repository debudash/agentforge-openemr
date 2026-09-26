# src/Patient/Cards/BillingViewCard.php

**Role:** the Billing card: balances, billing note, primary insurance summary.
**Size:** 92 lines. **Reached from:** `addCard(new BillingViewCard(...))` at demographics.php L1343 unless `hide_billing_widget`.

## Purpose and lifecycle

On render it computes patient balance, insurance balance, total, unallocated pre-payment and
collections balance with four `get_patient_balance`/`get_unallocated_patient_balance` calls
(L37-41), and passes the billing note and the primary insurance's name, copay and dates.

## Controls

- **Authorization:** `'acl' => []` (L17). The page skips the ACL check when the list is empty
  (demographics.php L1358), so **the balances are shown to anyone who can view demographics**; no
  accounting (`acct`) permission is required.
- **Escaping:** the template uses `|money|text` and `|text`.

## Database touches

Reads billing, payments and ar tables through the balance functions.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| BVC-01 | Medium | L17 | **Financial data without a financial permission.** |
| BVC-02 | Low | L21 vs L42 | **Collapse state never persists:** it reads user setting `billing_expand` but the card's id is `billing_ps_expand`. |

## What the port keeps

Outside the brief.
