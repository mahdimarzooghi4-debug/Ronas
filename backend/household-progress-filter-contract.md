# Ronas — owner-scoped Domestic observed technical queue

**Status:** LOCAL/TEST DEMO, GET-only, development Draft PR #9. There is no
real enrollment, household consent, qualified agronomy advice, planting plan,
agricultural eligibility or Business authorization.

## Read paths and user experience

- `GET /api/v1/domestic/household-intake/my-drafts/technical-progress`:
  existing Keycloak-verified, owner-only progress read now optionally accepts
  `technical_state=ALL|UNREQUESTED|EVIDENCE_REVIEW_REQUESTED|HUMAN_RESPONSE_RECORDED`,
  defaulting to `ALL`, plus existing `limit` (1..50), `after_ref` DEMO cursor,
  and optional `snapshot_sequence` returned by the first page.
- `GET /` in the **existing shared user/partner environment** has the matching
  `household_technical_state` filter when the same review-aware ledger is
  injected. Next-page links preserve the filter, `after_ref`, and snapshot
  watermark. Changing the filter starts a fresh snapshot. Case
  detail `/my-drafts/{ref}` and immutable version history
  `/my-drafts/{ref}/versions` remain the existing owner-only routes.
- When there is no review-aware ledger, the base immutable-owner queue is
  unchanged. Explicit non-ALL review filtering in that shell returns 422
  rather than fabricating a technical stage.

## Snapshot / access boundaries

The identical `SqliteSyntheticHumanReviewLedger` transaction first validates
the complete grant, historical and review audit chain, matches exact signed
`household` role and immutable case ownership, and selects *observed* review
state from the verified `technical_review_step` rows. Filtering happens
**before** bounded keyset pagination; only disclosed owner cases receive
`HOUSEHOLD_PROGRESS_WORKLIST` append-only read-audit events, in the same
transaction. No hidden-case counts, cross-household or Export identifiers,
private reviewer identities, actor digests, evidence / response references,
or review event times are returned.

Invalid filter/cursor is 422; ledger corruption, SQLite failure or missing
read-audit is 503 without any partial page. Invalid/expired JWT is 401.
Operator case grants cannot replace household ownership, and a grant
revocation cannot cancel genuine immutable owner reads.
The first page captures an ordinal over only this household's Domestic review
events. Later pages use it to reconstruct observed states from those events; a
concurrent request or response therefore cannot move a matching case between
pages during the traversal. The cursor does not expose the global audit
sequence or activity from another household or engine. Current ownership and
full-chain integrity are still checked independently on every page. The
snapshot ordinal is a consistency cursor, not an authorization token; values
outside this owner's current review-event range fail with 422.
Current filter semantics never imply a future review step or scientific
approval. A recorded human response is only a technical reference.

All crop, area, water, soil and location inputs remain unknown, plan remains
`NOT_AUTHORED` and every Business, professional-certification, consent and
scientific-approval flag remains false. No new actor role, frontend shell,
Business rule, write command, external authority or Production adapter.

## Verification and governance

Regression coverage: `backend/tests/test_owned_household_technical_status.py`
includes stage transitions, privacy, keyset and stable-snapshot pagination,
exact owner authentication, audit rollback, corrupt evidence fail-closed,
Persian UI filter navigation and detail/history no-approval semantics.
Business Domestic #2, Export #3 and Finance #4 gates remain OPEN.
PR #1 and #9 stay Draft/Open/Unmerged. No Stage, QA Gate, Ready for Review,
Merge, Release or Production is authorized.
