# Ronas — Technical Foundation v0.1 (PROPOSED / DESIGN ONLY)

**Status:** TECHNICAL DRAFT; **not** approved architecture, production admission or an operational Business contract.  
**Source of truth:** [Business Foundation](../business/00-business-foundation.md), [Domestic D-01..D-10](../business/01-domestic-engine.md), [Export E-01..E-09](../business/02-export-engine.md), [approved engine separation RON-DEC-001](../business/04-decisions-and-open-questions.md), [hybrid independent contracts RON-DEC-003](../business/11-export-multicontract-direction.md).  
**Scope:** dual-engine engineering foundation only. Legal incorporation, equity and shareholder matters are **not** a product-sprint dependency to be pursued in this work package. Operational contracts and permits, where applicable, remain separately gated.

## ۱. مرزهای پیشنهادی طراحی

| Context (provisional) | Responsibilities at Business level | Critical boundary |
| --- | --- | --- |
| Shared Product Discovery | Read-only catalog of capabilities with Source Ref and design status | No assumed activation, data sharing or operational gate approval |
| Domestic | Household onboarding/plot/crop, monitoring/harvest, local market, delivery, complaints, finance (D-01..D-10) | Independent data, eligibility, financial terms and approvals |
| Export | Professional supply, product/target market, independent contract families, QC, processing, shipping, finance (E-01..E-09) | Contract-specific title, seller, QC, product/destination and payment evidence |
| Identity/Consent (future) | Authentication, lawful access and consent record | Never deduce consent or access from appearance in another engine |
| Audit/Policy (future) | Versioned approvals and immutable decision evidence | Undefined policies must remain undefined; no synthetic approval |
| AI (future) | Only candidate recommendations after data/evaluation approval | No AI decision about QC, settlement, eligibility or purchase obligation |

**Shared product discovery is code-level infrastructure only**; it does not mean shared household/export partner identity, ledgers, approvals, bank accounts, record ownership or permissions.

## ۲. تکنولوژی این بسته (پیشنهاد قابل تعویض)

- **Python 3.12 + FastAPI + Pydantic**, in a narrow, testable backend read-only service.
- **pytest + TestClient** for backend contract/boundary checks; GitHub Actions for CI.
- **No database, user records, identity provider, payment provider, AI runtime, queue, file storage, postal service, exports or FX integration in this first slice.** Their technology and contract are intentionally not selected by this commit.
- A Persian RTL frontend is a future product requirement candidate; no UI stack or visuals have been approved or created here.
- OpenAPI generated for **only** read-only design discovery; these URLs are an internal technical proposal, not ratified operational interfaces.

## ۳. Actual committed Sprint 01 contract (read-only)

```text
GET /healthz
GET /api/v1/product/engines
GET /api/v1/product/engines/{engine_key}
GET /api/v1/product/engines/{engine_key}/capabilities
```

Engine keys are **exactly** `domestic` and `export`. Unknown keys produce 404 (no inferred fallback). Every catalog item is `DESIGN_ONLY` and every engine has `business_gate=OPEN`. Source references are document paths, not claims that a capability is implemented.

**Non-goals:** No POST/PUT/PATCH/DELETE product API; no sign-in/session, plot suitability, harvest quantities, marketplace stock/orders, money, FX, contract approval, export customs, QA clearance, recommendation model or synthetic operational datasets.

## ۴. Quality gates and scope

- Tests validate two engines, exact D/E document IDs, source references, mode `DESIGN_ONLY`, `OPEN` gate, unknown-engine failure, absence of write API and immutability.
- CI tests may pass without completing a **Business Gate**, Stage/QA, security assessment, legal/commercial contract or Production.
- Future feature contracts must link to real Business decision(s), users, acceptance criteria, evidence and explicitly approved permissions; no unapproved finance or safety defaults.
- This technical proposal is a **stacked Draft PR** based on the **unmerged Business PR #1 branch**; it must not be merged or deployed until explicitly requested and gated.

## ۵. Pending product decisions (not blockers for read-only discovery)

- Domestic pilot users/region/crops and expert-reviewed food safety; membership, sales, logistics, fee policy.
- Export product–destination, per-contract roles and ownership, processing/QC/permits, settlement.
- Shared authentication/authorization, consent, retention, verified business evidence, UI design.
- Validation and sequencing of implementation slices are documented in [Product Backlog](../product/00-backlog.md).
