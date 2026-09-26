# 0001. Build the new patient dashboard with React, TypeScript and Vite

Status: accepted (2026-09-25). Supersedes: none.

## Context

The brief asks for the patient dashboard's presentation layer to be ported to a modern framework
over OpenEMR's REST/FHIR API. The legacy page mixes SQL, authorization, HTML and JavaScript in one
2,080-line file, and Twig runs with autoescape off, which produced three stored-XSS sinks
(`.scratch/dashboard-modernization/02-bug-catalog.md`, BUG-009/010/011). Options were React, Vue 3,
Svelte, modern Angular, an SSR framework, Streamlit, or PHP with htmx (spec §3).

## Decision

A static single-page app in React 19 and TypeScript (strict), built with Vite. SMART login through
`fhirclient`; responses parsed with Zod; data fetched with TanStack Query; Bootstrap 4.6 CSS for
the existing look.

## Consequences

- React escapes by default; `dangerouslySetInnerHTML` is banned by lint (spec rule R3).
- FHIR responses are typed at the boundary, so missing fields fail at build or parse time.
- Adds a Node toolchain and a second deployable. The app lives in `dashboard/` with its own
  `package.json`, so it does not inherit OpenEMR's Node >= 24 requirement.
