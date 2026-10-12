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

## Local source-blob integrity / fail-closed drift detection (2026-10-10)

The source commit hash above is a historical Business PR #1 **commit**,
not proof of the current PR HEAD. The opt-in gate display now has a
separate, stronger **local file-level** check:

| Checked source path | Pinned Git blob SHA-1 |
| --- | --- |
| `docs/business/73-core-d1-e0-limited-scope-gate-decision-sheet.md` | `86da48af24adc49976921033eeb74eb3b67b5cbc` |
| `docs/business/61-finance-legal-evidence-workstreams-for-d0-e0.md` | `642f5b0e1d506d436c4f379a6ad0b1624b5bbb0c` |

`verify_pinned_business_sources()` reads exactly these two local
repository files, restricts resolution to the local checkout root,
computes the canonical Git blob identifier over original **bytes**
(including the Git blob NUL separator), checks each of the 19 evidence
ID/status pairs in the original source-table rows, and rejects missing,
changed, redirected, oversized, non-UTF-8 or otherwise inconsistent
files. Source-level statuses are not recomputed, improved, decided,
or reclassified by the app.

On success the read-only API additionally returns
`source_integrity_state=LOCAL_REPOSITORY_FILES_MATCH_PINNED_BLOBS`
and exact source blob identity in dossier detail. This means **only**
that the two files available to the test instance match the pinned
historical blobs, not that the live GitHub PR/Issues, business authority
or rights are still current. The existing
`PINNED_DRAFT_SNAPSHOT_NOT_LIVE` marker remains mandatory.

On any mismatch, GET list, GET detail and HTML gate-detail fail closed
with sanitized **HTTP 503**
`PINNED_BUSINESS_SOURCE_UNAVAILABLE`, withholding *all* outdated
evidence cards. The normal admin landing page continues to serve its
independent role/case read models but **hides the outdated gate links**
and shows a Persian integrity warning. Unassigned roles still receive
403/404 before source inspection. The default runtime has no gate
routes at all.

**Change protocol (human, not auto-upgrade):** if PR #1 or either file
changes, inspect the actual source diff and gate issue state; confirm
what the authorized Business review really decided; pin any new
snapshot to an exact revised source commit and both Git blob IDs;
update only source-accurate requirement IDs/statuses after separate
review; keep all `verified_here=false` and no gate PASS unless
real authorized evidence establishes it. Run all tests and full
exact-HEAD CI; retain old snapshots as Git history. Do not bypass a
red integrity check by changing a hash alone, guessing a status,
migrating unapproved evidence or claiming a verified live Gate.

Nine additional regression tests exercise source bytes, exact Git
objects, missing/altered files, redirected symlink, status mutation
even with a deliberately recalculated hash, sanitized 503 for API
and HTML, preserved independent admin work, and denial precedence.

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

`backend/tests/test_business_gate_evidence.py` contains **26**
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
