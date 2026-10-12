# روناس — نقشه اجرایی تجربه دو محیط و نخستین مسیرهای رابط کاربر

**Status: APPROVED TWO INTERFACE SHELLS BY RON-DEC-031 / PROPOSED UX CONTENT, FLOWS & SCREEN INVENTORY; NO IMPLEMENTED UI OR TECHNICAL ADMISSION**  
**Date:** 2026-10-10  
**Authority:** [RON-DEC-030/031](04-decisions-and-open-questions.md) and [role contract 75](75-target-digital-apps-and-role-panel-topology.md). The owner explicitly approved the **proposal of one user/partner interface + one unified administration panel** in the current conversation. This approval is for **business-facing experience packaging**, not UI screen designs, architecture/framework/mobile binaries/hosting or legal operation.  
**Scope references:** [D1/E0 decisions 73](73-core-d1-e0-limited-scope-gate-decision-sheet.md), [build-readiness 74](74-operational-build-readiness-audit-and-first-thin-slices.md), [Domestic Gate #2](https://github.com/mahdimarzooghi4-debug/Ronas/issues/2), [Export Gate #3](https://github.com/mahdimarzooghi4-debug/Ronas/issues/3), [Finance Gate #4](https://github.com/mahdimarzooghi4-debug/Ronas/issues/4); [draft prototype PR #9](https://github.com/mahdimarzooghi4-debug/Ronas/pull/9).  
**Not approved:** concrete pages, URL routes, navigation labels, IAM policy, data schema, Frontend stack, deployment, real PII consent collection, validated expert identity, marketplace, PSP, export contract, provider API, AI plan inference, Production. Panels #6/#8/#9/#13 must NOT reappear.

## ۱. تنها دو محیط برای همه نقش‌های دارای UI

| Environment ID | User audience | Approved containment | What it does NOT imply |
| --- | --- | --- | --- |
| **UI-01 — روناس / Shared User-Partner Experience** | Role #1 domestic household/producer; #2 local buyer; #3 agronomy expert; #4 equipment seller; #7 professional export supplier | **One common interface** containing five role views. Reuse only visual shell and permitted public content; independent Domestic/Export records and grants | One common data permission, shared contract, one database, a mobile-native app, seller activation or five separate deployments |
| **UI-02 — مدیریت روناس / Unified Administration** | #10 Domestic operations; #11 Export operations; #12 Finance; #14 general governance | **One admin panel** with four distinctly gated access areas; E0 human market research review belongs in the #11 Export operations area | Four admin apps, unconditional super-admin rights, cross-engine disclosure, QC approval, plan approval, actual PSP/FX control |

**API-only #5:** hub/courier partner interaction will be a separately governed integration contract **if** a real provider, scope, identity/authorization, idempotency and data rights are verified. **No portal, app or default endpoint** for #5.  
**No UI #6/#8/#9/#13:** independent QC officer, standalone export research specialist, foreign buyer and support/content roles are excluded **as distinct panels**. Legal QC, expert agronomic sign-off, buyer identity/contract obligations and customer obligations may still have to be evidenced **without inventing replacement portals**.

## ۲. Proposed minimal entry points and screen inventory — candidate, not approved page count

| Interface / access | Candidate view or user step | Status and essential boundary |
| --- | --- | --- |
| UI-01/#1 Domestic household | Public entry → consent-purpose explanation → user-declared cultivation context → correction of draft → draft preview | **First UI candidate CORE-D1-A**; purpose-limited consent and exact field policy not legally approved. Do NOT collect live household details |
| UI-02/#10 Domestic operations | Scoped intake draft review with provenance, gaps and referral to authorized reviewer | **First admin counterpart CORE-D1-A**; may NOT sign as agricultural expert or approve crop plan |
| UI-01/#3 Agronomy expert | In later D1-B: evidence review → proposed plan → approve/return with rationale → stage monitoring and revision | **Deferred** until real qualified expert, applicable scientific criteria and internal model evaluated; preserving history and human decisions mandatory |
| UI-02/#11 Export operations | Research question → cited sources / licensing caveat → findings / limitations → accountable human review / return | **First UI candidate CORE-E0-A**; E0 is not a buyer, sales order, pricing, exporter clearance or real contract. Former role #8 is NOT rebuilt |
| UI-01/#2 Local buyer | View verified public listings; future checkout/dispute concepts only | **Disabled/deferred**, requires independent seller approval, publication consent, food safety evidence and Finance #4 |
| UI-01/#4 Equipment seller | Contracted catalogue and actual sale/service obligations | **Deferred** until seller/legal/financial rights; no invented price, commission or invoice |
| UI-01/#7 Export supplier | Identity/capacity declaration and review of evidence | **Deferred** until exporter/supplier authorization and Export #3; declaration ≠ contract |
| UI-02/#12 Finance | Distinct Domestic and per-export-contract accounting review; no real funds actions | **Deferred** until FIN-001..007, actual source workbook, authorized reviewer and Finance #4 |
| UI-02/#14 Governance | Read-only audit, role assignments/review, explicit Business/technical gate provenance | Governance actions require *actual* authority; **no implicit global access** |

**UI behavior in absence of permission/evidence:** Do not create a working form that persists PII or contract data; display non-operational placeholders/demos only after UX/Technical decisions, visibly labeled as demonstrations. Hide or disable trading/money/export commitments; an unavailable workflow must not silently create a draft that looks like an approved plan, verified buyer, published edible offer or accepted contract.

## ۳. Six negative UX scenarios for first bounded build

1. **Domestic unknown consent:** #1 cannot submit live cultivation context without approved purpose/consent design; no implied consent from tapping a general login button.
2. **Domestic conflict:** #1 submits inconsistent cultivation facts; do not infer a corrected fact; #10 may flag review but cannot issue scientific approval.
3. **Unapproved agronomy:** #1 must not see a proposal as *validated cultivation advice* without qualified #3 review according to RON-DEC-015..021.
4. **Export absent source right:** #11 sees a source with a citation but no real reuse rights; E0 study remains a draft, with no published/reused restricted source data.
5. **Cross-engine role:** #10 Domestic Ops does not gain #11 Export or #12 Finance access merely because the admin panel is visually shared; #7 does not gain #1 household access.
6. **Forbidden portal resurrection:** #5 API-only and roles #6/#8/#9/#13 must not appear as separate navigation destinations; a 404/hidden navigation is not itself a security control, and any real endpoint still needs server-side rights.

## ۴. Implementation sequencing within the parent development process

**Business-approved topology ≠ Business Gate acceptance.** Before turning the above candidate navigation into actual API/UI components, the two independent Scope gates must have named Business owners, actual consent/source/legal evidence, negative acceptance scenarios and explicit decisions; Technical must separately approve architecture/security and the Product Backlog / Sprint. Prototyping [PR #9](https://github.com/mahdimarzooghi4-debug/Ronas/pull/9) contains **pure Python in-memory drafts only**, with no UI, persistence, server IAM or real user intake.

**First pair when admitted:** UI-01/#1 draft household intake **and** UI-02/#10 Domestic intake review. In parallel, UI-02/#11 E0 research with source provenance and human judgment. This preserves a single admin shell while avoiding a now-rejected independent #8 panel. Quality, finance, trade, shipping and AI automation are not invented or silently enabled.

**Decisions still genuinely OPEN:** responsive web vs PWA vs mobile native delivery, visual identity, accessibility/languages, actual IAM grants and whether one identity spans engines, screens and state transitions, data persistence/retention, lawful provider/API contracts, model/runtime approval, cost/operability and realistic test gates. None of these can be inferred from two UX containers.

**Final:** two approved experience shells, five external role views + four separate areas inside **one** admin panel; API-only logistics; no stand-alone QC/export researcher/foreign buyer/support portal; gated D1-A/E0-A first; no real service activation, no Production authorization.
