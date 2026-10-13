# Household surplus draft lifecycle (LOCAL/TEST)

## Purpose

Let an authenticated household create and revise a private Domestic surplus draft using an explicitly injected product schema. Draft content remains household-owned and versioned. This lifecycle does not create a public listing or authorize a sale.

## Data contract

- The product schema is supplied by the current application composition. The implementation must not invent product fields, units, price, availability rules, or quality criteria.
- A draft revision binds the household reference, offer reference, producer subject, schema reference/version/digest, canonical payload digest, revision, previous revision receipt digest, and an idempotency action reference.
- Only the current owner may read or revise the draft. A revision uses compare-and-swap against the expected current revision; stale writes return a conflict and never overwrite history.
- Replaying an action reference with identical command content returns the original receipt. Reusing it with different content is rejected.
- Historical revisions are immutable. A schema change requires a new revision and never silently reinterprets prior values.

## Security and state

- New drafts are private and unpublished. The published flag is always false in this lifecycle.
- The ledger exposes only owner-scoped read/write methods; HTTP and browser route composition remains a later integration step.
- Injected owner authority is checked on every read and write. Validation errors originate from schema rules and do not echo submitted values.
- The current surplus publication-readiness gate remains a separate, read-only evaluation. It must bind to the exact current offer revision and payload digest.
- Local/test persistence is not a production-storage approval.

## Verification

Tests cover owner isolation, role enforcement, injected-schema validation, stale revision conflicts, immutable history, schema-version binding, idempotent retry, conflicting replay, and the invariant that no draft transition publishes an offer.