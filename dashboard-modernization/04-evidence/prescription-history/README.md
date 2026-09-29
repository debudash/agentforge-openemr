# Prescriptions restored to Prescription History

Run 2026-09-26 on the local stack. The legacy Prescriptions card is headed "Prescription History"
and lists every prescription not discontinued, current or ended. The port had shown active ones
only (243 rows fewer across 46 patients in the 50-patient parity run).

## Change

- `dashboard/src/app/queries.ts`: the `MedicationRequest?intent=order` search no longer sends
  `status=active`.
- `dashboard/src/fhir/medicationRequest.ts`: `toPrescriptionList` keeps `active` and `completed`,
  drops `stopped`, sorts active first, and carries a `status`. OpenEMR reports an active row with
  any end date, past or future, as `completed` (`PrescriptionService.php` L181-183), so the card
  shows the record's status, not "past".
- `dashboard/src/cards/PrescriptionsCard.tsx`: a Status column; completed rows muted.
- `dashboard/tests/fhir.test.ts`: one test for inclusion, order and the stopped exclusion.

## Checks

- Lint, typecheck: clean. Vitest: 74 passed.
- The new test fails when the sort is removed and when stopped rows are let through.
- Parity, `PARITY_PIDS=10,9,5,27,4,26,35,46,44,16` (the patients with the most prescription
  history): 10 of 10 pass. Prescriptions match on every patient, 140 legacy / 140 port. No other
  card's verdict or items changed against the Phase 4 run. Per-patient results in `pids/`.
- The demo data has no discontinued prescriptions, so the stopped exclusion is covered by the unit
  test only.
- The 50-patient report in `../parity/` is the Phase 4 run and predates this change.
