# Sprint 01 — Dual-Engine Read-Only Foundation

**Status:** DRAFT CODE SLICE / no Stage or Release approval  
**Depends on:** open Business PR #1; technical proposal, not an approved marketplace architecture.

## Goal
Establish a runnable, test-covered, safe read-only backend for Ronas that exposes the existing **D-01..D-10** and **E-01..E-09** design vocabulary as distinct engines. Provide a documented proposed architecture and a separate backlog for each motor.

## In scope
- Package skeleton with FastAPI, Pydantic and typed immutable manifest
- `GET /healthz` and three read-only Product Discovery routes
- Source references and explicit `DESIGN_ONLY` / `OPEN` status
- Negative contract tests: unknown engines 404, any write 405, no operational routes or pricing
- GitHub Actions CI and document / backlog traceability

## Out of scope
Any real user account, registration flow, AI, agriculture recommendation, eligibility/QC pass, pricing, order creation, inventory allocation, payments, transfers, legal entity registration, export, provider integration, UI or deployment.

## Acceptance
- [ ] Exactly 2 independent engines and 19 document-linked capabilities
- [ ] All capability statuses DESIGN_ONLY and both business gates OPEN
- [ ] No operational write API; wrong engine 404; no guessed user/payment/export data
- [ ] Automated tests pass and CI is green on the exact PR head
- [ ] Draft PR and documented code review; no merge, Stage, Release or Production without explicit instruction

## Next logical package
Once reviewed, move to evidence-first identity and non-financial workspace contracts for Domestic and Export as distinct bounded contexts. Any operational action requires its own approved business contract and accountable actor.
