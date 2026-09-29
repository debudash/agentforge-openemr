# 0003. Vitals is the dashboard's extra section

Status: accepted (2026-09-25). Supersedes: none.

## Context

The brief requires the patient header and five cards, plus one more section of our choice. The API
also supports Appointments, Immunizations and Encounters (spec §6).

## Decision

Vitals: the latest vital signs with the date taken, from
`Observation?category=vital-signs`.

## Consequences

- A legacy Vitals card exists, so parity can be measured rather than asserted.
- US Core defines the vital-signs profile precisely.
- The legacy Vitals fragment has no authorization of its own (BUG-006, VTF-01); the new card gets
  its data from an API route that does, so the port designs that out.
