# Ronas — Product Backlog v0.1 | Two Independent Engines

**Status:** DRAFT / groomed from Business source, not authorized production commitments.  
**Traceability:** `docs/business/01-domestic-engine.md`, `02-export-engine.md` and `04-decisions-and-open-questions.md`.  
**Priority:** only Sprint 01 read-only foundation is admitted for nonoperational implementation; all future capabilities await their own contract/review. No inventing product thresholds, commissions, QC pass rules, export destinations or AI architecture.

## Shared / enabling work (proposed)

| ID | Capability | Dependencies / acceptance |
| --- | --- | --- |
| CORE-001 | Dual-engine capability discovery (Sprint 01) | GET-only manifest for both engines with source, status and open Business gate; tests, CI |
| CORE-002 | Identity/authorization and consent contracts | Users/roles, lawful access, data boundary, retention and audit acceptance |
| CORE-003 | Evidence/approval foundation | Versioned decisions, accountable actors, no synthetic approvals |
| CORE-004 | Frontend navigation in Persian RTL | Approved screens, mobile/browser accessibility, both engines distinct |
| CORE-005 | Observability/security baseline | Threat model, request trace, dependency checks, rollout gate |

## Domestic — candidate backlog, separate Business and Product Gate

| ID | Business | Proposed slice | Critical approval or evidence |
| --- | --- | --- | --- |
| DOM-001 | D-01 | Household/account domain | Terms, privacy, consent, eligibility |
| DOM-002 | D-02 | Plot suitability workspace | Household data permissions, safety of plot/common area |
| DOM-003 | D-03 | Crop planning and learning | Expert-reviewed recommendations, data provenance; AI undecided |
| DOM-004 | D-04 | Equipment supplier catalog | Seller of record, returns, payment responsibility |
| DOM-005 | D-05 | Crop observations | Observation provenance, expert review, errors |
| DOM-006 | D-06 | Harvest journal | Food safety, quantity/quality evidence, no automatic public listing |
| DOM-007 | D-07 | Local marketplace | Seller, price/consent, food safety, orders |
| DOM-008 | D-08 | Hub and fulfillment | Responsibility, temperature/spoilage, proof and dispute |
| DOM-009 | D-09 | Dispute evidence and review | Complaint rights, decision authority, remedy and audit |
| DOM-010 | D-10 | Payments and accounting | PSP/finance contracts, tax, reconciliation, no fake settlement |

## Export — candidate backlog, independent Business and Product Gate

| ID | Business | Proposed slice | Critical approval or evidence |
| --- | --- | --- | --- |
| EXP-001 | E-01 | Supplier qualification dossier | Evidence/credentials and human approval |
| EXP-002 | E-02 | Exportable product/specifications | Product/market, lab standards, approved specifications |
| EXP-003 | E-03 | Demand research workspace | Buyer authenticity, country, evidence and noncommittal leads |
| EXP-004 | E-04 | Multi-contract dossier | RON-DEC-003, distinct agreements, liability and ownership |
| EXP-005 | E-05 | QC evidence | Reviewer authority, target regulation and traceability |
| EXP-006 | E-06 | Processing batches | Processor responsibility, permits, quality/loss |
| EXP-007 | E-07 | Foreign trade agreement | Buyer/seller, payment, currency and terms |
| EXP-008 | E-08 | Shipment and export evidence | Legal exporter, customs, insurance, delivery |
| EXP-009 | E-09 | Export accounting and split | Contract-specific fees/partnership, FX, no double counting |

## Development rule

Each item needs a scoped business rule, owner, source, permissions, adverse scenarios, testable acceptance and explicit code authorization. Work in parallel, but never convert one engine's approvals into another's. Separate from the registered legal-form follow-up; product engineering need not pursue equity/incorporation questions to construct a read-only foundation.

Next permitted engineering candidate after CORE-001: review **CORE-002/CORE-003** for a non-financial, evidence-grounded workspace; do not begin real user storage/permissions before approved product contract.
