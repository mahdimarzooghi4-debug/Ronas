# Ronas — Export research case version history and filter-preserving navigation

**Status:** only opt-in LOCAL/TEST DEMO; Draft PR #9. This is a
read-only usability feature, NOT authorized export research, source rights
clearance, professional certification, supplier qualification, commercial
approval, market findings, orders, pricing, real customer data or trade.

## Existing unified Export Admin journey

A signed `export_ops` operator with an explicit **current case-specific**
grant uses the existing `GET /admin/export/research` filtered queue.
Each case link now retains the active `technical_state` and `after_ref`
navigation context. The existing case detail at
`GET /admin/export/research/drafts/{ref}` displays only actual redacted
technical review event names in Persian; it links to the synthetic case
version history, and returns to the same selected queue filter/cursor.
No new panel or separate export-research user role exists.

New GET-only endpoints within the same bounded Export context:

- `GET /api/v1/admin/export/research/drafts/{ref}/versions` — signed
  versioned immutable synthetic case history with only `version_numbers`,
  per-version `is_current`, `DRAFT_ONLY`, provenance and conservative
  false Business flags; never previous-version payloads or raw source refs.
- `GET /admin/export/research/drafts/{ref}/versions` — authenticated,
  Persian RTL version timeline using those same authorized records and
  retaining queue/detail navigation context.

`technical_state=ALL|UNREQUESTED|EVIDENCE_REVIEW_REQUESTED|HUMAN_RESPONSE_RECORDED`
and optional `after_ref` on detail/history pages are validated solely for
navigation. They never widen permissions or affect the case record. The
filtered list and each detail/version page **recheck** current grants rather
than trusting the original list link. A previously valid signed JWT or
browser session alone never grants an Export case.

## Transaction / integrity / disclosure

`SqliteSyntheticHumanReviewLedger.read_export_research_version_history`
runs a single verified `BEGIN IMMEDIATE` transaction: full audit/review/grant
verification; signed `export_ops` role plus exact scoped grant and live
revocation check; exact `case_history` comparison to the immutable seeded
history, with current maximum version matching the actual case; minimal
history projection; and an append-only
`EXPORT_RESEARCH_VERSION_HISTORY` READ_ALLOWED/READ_DENIED event in the same
transaction. Failures to verify or append roll back the read and respond 503,
never a partial page. Wrong role/unassigned/revoked/non-Export/missing ref
returns indistinguishable 404; missing/forged identity is 401. No HTTP
mutation is introduced. Default runtime is still unmounted without explicit
Keycloak and the same synthetic review ledger.

`version_numbers` are only numbers from **PRESEEDED_IMMUTABLE_FIXTURES**;
they do **not** imply that users edited data or establish when/what changed.
The synthetic source ref remains a display-only, legally unverified
reference on the existing authorized case detail, **never** in version
history. Raw reviewer IDs, evidence/request/decision refs, historic
timestamps, verified country/product/HS, pricing, buyer, report, commercial
or source-rights approvals do not appear. Even
`HUMAN_RESPONSE_RECORDED` is a recorded technical reference only.

Case navigation is request-time: when grants/review status change between
visits, the next access is independently rechecked; the old list is not a
frozen authorized snapshot. An operator can explicitly choose another
filter, but cannot infer any hidden-case count.

## Verification and gates

Regression: `backend/tests/test_export_research_queue.py`, eleven additional
tests covering seeded [1,2,3] lineage, independent current grants,
revocation, atomic audit failure, tampered history, no write endpoints,
filtered UI/detail/history navigation, session/logout, invalid context and
concurrent revoke/read. Original queue and case APIs remain compatible.
Existing export case queue browser error handling also preserves integrity
failures as 503 rather than wrongly treating them as validation 422.

Business Domestic #2, Export #3 and Finance #4 are OPEN.
Both PR #1 and PR #9 remain Draft/Open/Unmerged. No Ready for Review,
Merge, Stage, QA Gate, Release Approval or Production is authorized.
