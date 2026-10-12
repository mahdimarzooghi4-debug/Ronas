# روناس — ممیزی کد موجود و کوچک‌ترین بخش‌های محصول اصلیِ قابل آماده‌سازی برای ساخت

**Status: READ-ONLY AUDIT + DRAFT FIRST-BUILD SCOPE OPTIONS / NO BUSINESS GATE OR TECHNICAL APPROVAL**  
**Date:** 2026-10-10  
**Inspected Business HEAD:** `be3db57b15c43bec2dcbe2d90724c628e2d5d6f4`; main `d58984710bbe8b9616111a40b4911abf284a3427`; Business PR #1 Draft/Open/Unmerged.  
**PR #6 exploratory code:** `fb1c6c3b84b5ea1e0ace9b1e95754ba70a32419d`, Draft/Open/HOLD; **two completed SUCCESS workflows** on that exact PR SHA (technical CI only, never Stage or Business Gate).  
**PR #8 Technical discovery:** `8c83edde7993d6da5a846dd2b36971756f2e127e`, Draft/Open; based on **older** Business tree, not a current signed Technical Architecture; no recorded workflow run for exact SHA in reviewed GitHub Actions query.  
**Source of Business truth:** [Domestic 70](70-core-domestic-operational-scope-and-business-acceptance.md), [Export 71](71-core-export-operational-contract-and-readiness.md), [critical path 72](72-core-delivery-critical-path-and-business-gate-readiness.md), [bounded gate decision sheet 73](73-core-d1-e0-limited-scope-gate-decision-sheet.md), [decisions](04-decisions-and-open-questions.md); gates [Domestic #2](https://github.com/mahdimarzooghi4-debug/Ronas/issues/2), [Export #3](https://github.com/mahdimarzooghi4-debug/Ronas/issues/3), [Finance #4](https://github.com/mahdimarzooghi4-debug/Ronas/issues/4) OPEN.

## ۱. آنچه واقعاً در PR #6 وجود دارد — در برابر آنچه هنوز نیست

| Exact inspected artifact | Directly verified functionality | NOT supplied / must NOT be claimed |
| --- | --- | --- |
| `backend/ronas/catalog.py` | Immutable `DESIGN_ONLY` catalog: Domestic D-01..D-10, Export E-01..E-09; gate `OPEN`; exact engine lookup | Household record, crop-plan version, expert decisions, crop reports, harvest/offer, export Opportunity or market-source evidence, contracts, finance |
| `backend/ronas/app.py` | `GET /healthz`, `GET /api/v1/product/engines`, `GET /api/v1/product/engines/{engine_key}` and `.../capabilities`; read-only descriptions | POST or other domain mutations, actual authentication/consent, CRUD, proof/quality/approval, external integration, persistence |
| `backend/tests/test_product_discovery.py` | Tests only for public catalog, engine isolation, read-only verbs, no sensitive design data | No real operation, privacy authorization, legal gate, production-quality evidence, Stage/Production proof |
| [PR #8 discovery](https://github.com/mahdimarzooghi4-debug/Ronas/pull/8) | Candidate contexts, independent data/consent/evidence questions, architecture alternatives and gate requirements | No approved model of data, architecture, stack, API, UI, hosting or implementation sequence |

**Verdict:** the existing FastAPI surface is **not a head start on actual household or export workflows** except as an unapproved sample of discovery-style code. Do not build CORE-D1/E0 by pretending that the public capability catalog is a domain service; do not merge PR #6. Green tests there are useful for that restricted code only. The Technical design alternatives in PR #8 should be **refreshed against current Business v0.38 and 70–74 if/when Technical admission is authorized**, not silently adopted today.

## ۲. First thin slices that avoid waiting on full AI Training / trade

| Proposed slice **for owner Business discussion, not chosen** | Value demonstrated by a first real product | Exact limited boundary | True evidence blocker today |
| --- | --- | --- | --- |
| **CORE-D1-A — Household intake & consent evidence only** | A lawful household could declare interest and provide purpose-bound cultivation-space facts; corrections are attributable | Only identity/rights/scoped intake and recording source/consent if explicitly approved. **No AI proposal, plan approval, expert sign-off, public harvest, marketplace or payment**. This is **NOT a human-only substitute** for RON-DEC-015..021. | Domestic #2 scoped authorization, real audience/region, personal-data consent/retention/authority, approved data fields, actor privileges; no production collection today |
| **CORE-D1-B — Personalized cultivation review / monitored plan** | Main Domestic promise: household-specific AI proposal → real expert review → stage observations and revisions | Requires internal valid AI runtime/adequate scientific evidence, accountable expert and version/decision lineage. **Never auto-approve a draft or treat empty model as a valid plan**. | Missing actual qualified expert, reviewed scientific criteria, rights-cleared model/data, household context, Technical contract and Domestic #2 |
| **CORE-E0-A — Human-owned, source-backed market opportunity report** | Researcher records product–destination question, source/date/unit/limitations and a review; research result is **not a commercial opportunity guarantee** | **No AI required to complete a human research report**; no buyer validation, procurement, signed contract, shipping, currency, payment, exporter-of-record or Domestic data. No product/HS/destination may be invented. | Export #3 scoped authorization, human-selected research question and real data-use/republication rights, qualified report reviewer and owner |
| **CORE-D2 / CORE-E1 — Public trade, logistics and money** | Eventual commercial value | Only with valid seller, product-specific quality authority, lawful buyer/supplier/exporter, separate contracts, transport and money rules | Domestic #2 + Export #3 **as relevant** + Finance #4, FIN-001..007; currently BLOCKED |

**Recommendation limited to prioritization:** work the **CORE-D1-A intake/consent contract** and **CORE-E0-A human-research contract** **in parallel for evidence**, since neither requires us to fabricate an AI model or activate trade. The complete CORE-D1-B main cultivation plan is *not* deferred as a business objective: retain it as a dependent core slice, with RON-DEC-015..021 controls. This is a candidate contract decomposition; it **does not mean the owner approved D1-A or E0-A for build or for processing real personal data**.

## ۳. Concrete negative cases needed at gate review (not code tests yet)

- **D1-A/CONSENT:** Declining/not proving informed purpose-scoped consent blocks storing purpose-bound household context; safe introductory public content may remain separate; exact contract still OPEN.
- **D1-A/ACCESS:** A person or Export role must not access/modify Domestic household information by mere shared login; actual role/grant and privacy policy still OPEN.
- **D1-B/INPUT:** Missing/contradictory required context cannot be guessed away or turned into an expert-validated plan.
- **D1-B/REVIEW:** A proposed AI plan without qualified expert approval is NOT a valid operational plan. Wrong prior data blocks new advice from old version and preserves original historical evidence.
- **E0-A/SOURCE:** A report missing a legally usable, dated source/HS/unit/context cannot be claimed verified; the reviewer must identify uncertainty and conflicting data.
- **E0-A/LEAD:** A market hypothesis, list of companies or 'interest' is not a real buyer, quote, order, export obligation or collected money.
- **CROSS-ENGINE:** Neither identity commonality nor source availability grants automatic D1→E0 reuse; no household/contract confidential data in training.
- **ALL/FINANCE:** Evidence report, intake or draft cannot create bank operations, payments, inventory, quality/edible-food certification or export logistics.

## ۴. Gate blocker compression — four factual inputs, not a new document cycle

| Decision/evidence input needed next | What it genuinely unblocks | Owner/reviewer evidence status |
| --- | --- | --- |
| **A. Explicit choice of limited review slices and exclusions** | Determining which Scope will even be assessed first by Domestic #2 and Export #3 | **PENDING OWNER DECISION**, no gate closure |
| **B. Household consent/authority + audience/region/fields** | Possible CORE-D1-A intake contract; **never first live PII collection on draft authority** | **NOT VERIFIED** |
| **C. Export research question (real product–destination) + rights/reviewer** | Possible CORE-E0-A research report contract; **no guaranteed market/buyer** | **NOT VERIFIED** |
| **D. Accredited expert/model, trading/QC/Finance proofs** | CORE-D1-B full plan, CORE-D2 marketplace, CORE-E1 trade, and actual financial services | **NOT VERIFIED; specific gates remain OPEN** |

These are *evidence inputs*, not an invented administrative approval process. Precise Software/API/Schema, technology choice, security implementation, production service, model and work estimates remain Technical decisions **after** the corresponding gate.

## ۵. What is allowed now, and what is not

**Allowed in current Business phase:** owner decision on the **review priority** of CORE-D1-A and CORE-E0-A, gathering real consent/rights/reviewer/source evidence, a written scoped gate record including exclusions for #2/#3 and genuine Finance #4 evidence review. Read-only technical discovery may only document options.

**Not allowed:** treating ‘بعدی’ as approval to select MVP/Technical stack, turning PR #6 into real services, merging either PR, coding CRUD/domain APIs or ingesting real households/contract data, assuming AI training is ready, starting real trade/settlement or declaring any gate PASS.

**Next useful move:** Ask the owner **one coherent choice**: review CORE-D1-A (household consent/intake) and CORE-E0-A (human-owned source-backed market research) as two strictly separated candidates for future independent gated Technical admission; **not** to launch AI, marketplace or export contracts. Then obtain actual minimum evidence for each and a signed scoped Business gate decision before Technical work.

**Final status:** Product-code audit COMPLETE / PR #6 DESIGN-ONLY / PR #8 DISCOVERY-ONLY / MAIN-OPERATIONAL SLICES CANDIDATE / NO APPROVED SCOPE / NO GATE PASS / NO CODE AUTHORIZATION.
