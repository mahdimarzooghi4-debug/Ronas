# Ronas — E0 research question authoring in existing Export admin (LOCAL/TEST)

**Status:** Synthetic-only opt-in technical experiment, Draft PR #9. Export Business Gate #3 and Finance Gate #4 remain open; neither a research task nor a real product–destination scope has been approved.

## User-value slice

A Keycloak-verified `export_ops` operator who holds a **current explicit grant** on an Export DEMO case can submit an *unverified preliminary research question* associated with that case:

`POST /api/v1/admin/export/research/drafts/{ref}/local-test-question`

Strict JSON: `action_id`, `expected_case_version`, `expected_question_revision`, `product_ref` and `destination_ref`. The last two **must** be synthetic `DEMO-PRODUCT-*` and `DEMO-DEST-*` reference tokens; no actual country, crop, HS, buyer, commodity, trade, licence, source contents, free text, personal data, commercial price or research finding may be supplied. The preseeded Export case provides its existing **UNVERIFIED** source pointer. No cross-engine source or geographic inference is possible.

Unlike earlier static Export queue/detail pages, the question can now be **authored, amended, and retrieved** with an incrementing draft-question revision (0 → 1 → 2). A `409 EXPORT_LOCAL_QUESTION_CHANGED` rejects stale case or question revision, conflicting action retry, and attempting an old replay after later amendments. Exact-head safe retry is idempotent. Each write joins the existing private local ledger's case-specific grant check, question record and append-only audit event in one SQLite transaction; audit/hash/row-lineage checks run on reopen, and no second ledger is introduced.

The existing signed GET `/api/v1/admin/export/research/drafts/{ref}/workspace` carries `local_test_draft_question` when recorded; the original unknown `research_question.product/destination/hs_code` remains **null**. The existing single administrative UI at `/admin/export/research/drafts/{ref}` now displays unverified DEMO question refs and current question revision, not an extra panel. The UI intentionally offers no mutation form until a CSRF-protected browser action contract is separately approved; the POST **requires explicit signed Bearer** and rejects cookie-only calls.

## Hard restrictions

The operator's signed role alone is insufficient. The current exact-case grant is checked in the same transaction; revoked/other-case/other-engine returns 404, unsigned requests 401, invalid reference command 422, stale expected revisions 409, and tampered/incomplete source or audit causes sanitized 503. No successful mutation may survive audit insertion failure. No approval/refusal decision, buyer verification, research publication, source-rights clearance, trade promise, invoice, payment, AI runtime or Production activation is added.

This local synthetic storage and toy reference vocabulary are **NOT** a real research report, verified source or authority to conduct actual Export research. Future real E0 needs separately approved product–destination, evidence rights, record retention, expert decision, and controlled document workflow. No Stage, QA Gate, Release, Merge or Production is authorized.
