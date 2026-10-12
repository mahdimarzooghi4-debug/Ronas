# Ronas — Combined Personal Domestic Partner Preparation (LOCAL/TEST)

**Status:** scoped synthetic GET-only development on Draft PR #9.
This is an individual navigation and missing-placeholder view, **not**
Business readiness, personal registration, identity verification,
matching, buyer demand, inventory, source rights, suitability, trade,
order, payment, scientific advice, or consent.

## User journey in the existing shared user/partner environment

A single signed user can hold `local_buyer`, `equipment_seller`, or
both roles. Previously they entered each role's individual self-preview;
there was no single private page showing only their **independently
authorized** DEMO preview slots. This slice adds:

- `GET /api/v1/domestic-partners/my-preparation` — compact personal
  projection containing only currently accessible role-specific DEMO
  references and their version and *unknown* display slots.
- `GET /domestic-partners/my-preparation` — Persian RTL counterpart,
  linked from both pre-existing `/workspace/local_buyer` and
  `/workspace/equipment_seller` role pages; each visible role links to
  its own existing `/local-buyer/my-preview` or
  `/equipment-seller/my-preview` page.
- No new frontend environment or panel; the existing two-environment
  rule remains unchanged.

The `SyntheticDomesticPartnerWorkspace.own_preparation_overview`
method recomputes each role's personal preview via the existing signed
`(role,subject)` seed and current, independent
`(role,subject,ref,version)` authority. Denied, missing, or unsigned
roles are omitted **without any count or identifiers of hidden roles**.
A single authority error invalidates the **entire** response (503),
not a partially disclosed overview. A dual-role signed subject losing
the `local_buyer` grant retains only its *separately authorized*
`equipment_seller` view. No other subject's or household's profiles,
Export records, provider refs or grant metadata are read.

## Semantic boundaries

All personal preparation placeholders remain `null` in the
existing `ronas.domestic-partner.self-preview.v1` contract.
`unknown_display_slots` in the new
`ronas.domestic-partner.preparation-overview.v1` is **only a listing
of these unfilled DEMO presentation keys**, not legally necessary intake
fields, a task list, scientific/commercial completeness or an onboarding
form. Every role's `business_readiness`, and the global overview's,
is `NOT_EVALUATED` — intentionally **not** READY/BLOCKED/PASS/FAIL.
Commercial actions, data submission, counterpart matching and real data
are `false`. An unfilled field is not a guessed negative real-world
fact and no score, eligibility, approval, offer, match or stage transition
is calculated. No owner, buyer/seller or household link is fabricated.

An authenticated but unrelated signed role receives 404; a signed
Domestic partner with no currently authorized synthetic seed receives
an empty `items` list (not an invented record); no/expired/forged token
or invalid browser session is 401; current authority failure is a
sanitized 503; POST/PUT/PATCH/DELETE are 405. Default runtime does
not mount these routes without an explicitly injected local workspace,
Keycloak browser and signature verification. CSP and no-store remain
enabled. All navigations re-check live authority.

## Test and governance

`backend/tests/test_domestic_partner_self_preview.py` includes nine
additional focused tests: two-role personal view, per-role isolation,
role-specific current grant revocation without collateral effects,
provider error returning no partial profiles, absent roles and seeds,
Persian dual-role and single-role navigation, session logout, role
denial, API/browser default-off behavior and mutation rejection.

Business Gate #2 Domestic, #3 Export, #4 Finance remain OPEN. New route
is **not an admission of CORE-D2 or D-04**. PR #1 and PR #9 remain
Draft/Open/Unmerged. There is no Ready for Review, Merge, Stage, QA Gate,
Release Approval or Production authorization.
