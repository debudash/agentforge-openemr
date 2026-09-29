# 0005. Create a restricted test user on the dev stack only

Status: accepted (2026-09-25). Supersedes: none.

## Context

The Critical and High findings are about users doing what they should not be allowed to. The
dev stack's users (`admin`, `doctor1`) hold the permissions those checks would deny, so the bugs
cannot be reproduced with them (ADR 0004).

## Decision

Create one or more users on the local dev stack with only the permissions each reproduction
needs (for example, patient read without demographics write). Never on Railway.

## Consequences

- The findings move from "verified by code reading" to reproduced, with a test each.
- The users and their passwords are local only and recorded in a gitignored file, like
  `copilot/.local-doctor1-pass`.
