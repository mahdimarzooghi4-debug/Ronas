# Ronas: bounded offline draft logic and two-interface UX prototype

Business decisions RON-DEC-030 and RON-DEC-031 authorize exactly two user-interface experience shells: one shared users/partners environment for role views #1 household/producer, #2 local buyer, #3 agronomy specialist, #4 equipment vendor, #7 professional Export supplier; and one unified administration environment, with distinct permission domains #10 Domestic Ops, #11 Export Ops, #12 Finance, #14 Governance. Role #5 is future API-only; there are NO dedicated panels for #6 QC, #8 export research specialist, #9 foreign buyer or #13 support/content.

## Interactive local demonstration — safe synthetic data only

Start the sample site **only on local loopback** from the repository root:

```sh
python -m http.server 8765 --bind 127.0.0.1 --directory prototype/ui
```

Open http://127.0.0.1:8765/index.html and follow the top navigation to http://127.0.0.1:8765/admin.html in the **same tab**. This is Python's built-in **static file server**, not Ronas API, customer signup, Identity/Consent service or a Production deployment.

- In the household shell, click **ساخت پیش‌نویس نمایشی** to prepare **DEMO-H01**; the state is always **evidence required**, NEVER consent verified or a cultivation plan approved.
- In the admin shell under Domestic, view the same synthetic demo draft and click **علامت‌گذاری نیاز به اصلاح نمونه**; this flags a fake correction scenario but is NOT an authenticated official reviewer decision.
- In Export admin, click **ایجاد پژوهش ساختگی** then **ارجاع نمونه برای بررسی انسانی**. The fixed **DEMO-SOURCE-01** is *not a real source*; rights remain unverified. No real buyer, HS code, export or contract is created.
- Use **پاک‌کردن وضعیت ساختگی نشست** to reset. Changes are constrained to a strictly validated, synthetic `sessionStorage` record of the current browser tab; there are **no arbitrary text inputs or any server submissions**. Opening the pages directly from local `file://` URLs may disable cross-page session storage; prefer the loopback command above.

No real household names/addresses, consents, partner or market data should be entered because the sample has no live collection path. Navigational/admin buttons **do not implement authentication or privilege enforcement**. The production-oriented frontend and backend architecture, database and identity provider remain undecided.

**CI verification:** `python -m unittest discover -s prototype/tests -v`, `python -m compileall -q prototype/ronas_core`, `node --test prototype/tests/test_demo_model.mjs` (Node 22). These test local synthetic transitions and static markup, not visual browser/Stage/security QA.

Browse locally using prototype/ui/index.html and prototype/ui/admin.html. These are **interactive local-only Persian RTL demonstrations** for fixed synthetic placeholders DEMO-H01 and DEMO-SOURCE-01. Navigation and limited demo state transitions work with local JavaScript; pages contain no forms, free-text fields, fetch calls, external resources, real personal data, trade, payment, operational identity or permission checking. The admin sidebar is NOT access control. Specific screen fields and channel choices are prototypes, not approved product/technical schemas.

CORE-D1-A examples: the household interface introduces consent and cultivation context without collecting any data. The Domestic admin area views a dummy intake record; no crop-plan approval or expert impersonation occurs. CORE-E0-A: research with unknown product/destination, a dummy cited source and unverified rights is visible within Export admin #11, without reinstating role #8 as a portal. Buyer, QC, logistics, payments and contracts stay deferred or API-only as decided.

The two pre-existing Python modules in prototype/ronas_core are immutable in-memory draft validators and are NOT connected to these pages. The prototype establishes no FastAPI, React, Native, database, auth, frontend framework or operational architecture choice.

Test (Python 3.12): python -m unittest discover -s prototype/tests -v
Compile check: python -m compileall -q prototype/ronas_core

Every source, household and market reference in the tests/UI is fictitious. Do not use personal, financial, contractual or confidential real-world data in this experiment. Legal consent texts, rights to market-source data, responsible expert and human review identity, Business gates, Technical ADRs, persistence, actual partner API, Production hosting and security still require independent approval.

Business authority for UX structure: docs/business/75-target-digital-apps-and-role-panel-topology.md and docs/business/76-two-interface-ux-entry-points-and-first-slice-journeys.md on business/ronas-foundation-v0-1. Domestic Gate #2, Export Gate #3, Finance Gate #4 remain OPEN. PR #9 Draft/Open/Unmerged; PR #6 exploratory HOLD, PR #8 discovery-only. No live deployment, merge, Stage or Production is authorized.
