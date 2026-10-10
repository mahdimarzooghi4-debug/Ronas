# Ronas — pinned Business gate-evidence read model (LOCAL/TEST)

**Status:** Source-pinned DRAFT research and diagnostic view only; it is NOT
an authoritative Business gate, production readiness test, live GitHub issue
status, evidence verification, admission, or approval. Documented on
2026-10-10 in open Draft PR #9.

## Source identity and bounded contract

The immutable snapshot is transcribed from Business PR #1 exact HEAD
`5492690e91955e64353824ffa4ec3250286fdf68` into
`ronas_api/business_gate_evidence.py` and carries that full commit SHA
on **every** response. The user-visible value
`snapshot_state=PINNED_DRAFT_SNAPSHOT_NOT_LIVE` is deliberately required.
An OPEN status means **OPEN in the cited draft source**, not a live
certified state of the GitHub issue and not a decision to keep it OPEN
if an authorized owner later changes it. Recheck PR #1 and issues
#2/#3/#4 before any actual admission review. Code/CI never promotes a
source-status entry or silently updates its source version.

- **Domestic, Gate #2:** D1-B-01..06 from
  `docs/business/73-core-d1-e0-limited-scope-gate-decision-sheet.md`;
  target population/region/product, consent/data rights, verified
  agronomy expert, internal AI and expert review, observations/history,
  actual Human Business gate decision. **Six proposed evidence items;
  not a deployed Domestic case workflow**.
- **Export, Gate #3:** E0-B-01..06 from the same Business decision sheet;
  real product/destination research question, source license/rights,
  authorized review owner, separation of research from trade,
  report/acceptance evidence and separate Export admission. **Six
  proposed items; no verified buyer, source use, research result,
  transaction or cross-engine data reuse**.
- **Finance, Gate #4:** FIN-001..007 from
  `docs/business/61-finance-legal-evidence-workstreams-for-d0-e0.md`;
  model scope, capital classification, membership-period semantics,
  contract-specific revenue, dated source rates, actual cashflow and
  unit economics. **Seven unresolved source discrepancies; no
  invented financial figures, FX, cost, revenue or settlement**.

The evidence `source_status` strings are copied from the referenced
source cards, including distinctions such as approved *direction*
versus absent executable model, and proposed contract versus accepted
contract. Every item returns `verified_here=false`; no real evidence,
person, file, cost or approval is stored or collected. The snapshot has
no POST, upload, delete, decision command, timer, refresh job, model
inference or evaluation threshold.

## Admission and authorization

The endpoints are mounted **only** with the explicit
`BrowserOIDC`/Keycloak-configured development app, inside the
**existing unified admin environment**:

- `GET /api/v1/admin/gate-evidence`: role-filtered three-domain
  summaries, each showing OPEN-at-source and pinned revision
- `GET /api/v1/admin/gate-evidence/{domain}`: source-reference cards
  with evidence ID, text, original status and unverified marker
- `GET /admin/gate-evidence/{domain}`: Persian RTL HTML detail
  reachable from the existing single `/admin` panel

A signed `domestic_ops` token can read only Domestic metadata;
`export_ops` only Export; `finance` only Finance. A signed
`governance` role may read all three **public Business gate metadata**
sections, not operational cases, personal records, grant/review history
or financial transactions. User/partner roles receive 403 on the
aggregate and 404 on detail; unknown and unauthorized detail are the
same 404. Missing/invalid JWT or revoked browser session gives 401.
An explicit invalid Bearer token never falls back to a cookie.
All HTML links use exact allowlisted source paths and the pinned source
SHA; user parameters cannot set repo URLs. GET responses retain
`Cache-Control: no-store`, and HTML enforces the existing CSP.

Neither PR #9 nor the default `create_app(KeycloakConfig.from_environment())`
changes Business decisions or deploys an admin portal. The endpoints
are opt-in local/test presentation, not live approval infrastructure.
The actual signed Business record and real source rights/consent remain
governed externally.

## Verification and open blockers

`backend/tests/test_business_gate_evidence.py` contains **17**
offline integration checks: 19 canonical source IDs, pinned SHA and
source status fidelity; independent three-domain role isolation;
governance metadata-only access; 401/403/404 boundaries; multi-role
union; forgery/expired token/logout; default opt-in; immutable output;
no POST or auto-PASS; version-pinned HTML links and strict CSP.
All test JWTs are locally generated against synthetic subjects.

No independent human reviewer, legal data-use rights, Domestic
qualified specialist, selected Export research question, validated
Finance workbook or source correction was evidenced by this code.
Business gates **#2, #3 and #4 remain OPEN** in the inspected draft.
PR #1 and #9 remain Draft/Open/Unmerged; no Stage, QA Gate,
Production, release or merge is authorized.
