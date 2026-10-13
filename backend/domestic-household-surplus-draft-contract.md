# Household surplus draft lifecycle (LOCAL/TEST)

## Purpose

Let an authenticated household create and revise a private Domestic surplus draft using an explicitly injected product schema. Draft content remains household-owned and versioned. This lifecycle does not create a public listing or authorize a sale.

## Data contract

- The product schema is supplied by the current application composition. The implementation must not invent product fields, units, price, availability rules, or quality criteria.
- A draft revision binds the household reference, offer reference, producer subject, schema reference/version/digest, canonical payload digest, revision, previous revision receipt digest, and an idempotency action reference.
- Only the current owner may read or revise the draft. A revision uses compare-and-swap against the expected current revision; stale writes return a conflict and never overwrite history.
- Replaying an action reference with identical command content returns the original receipt. Reusing it with different content is rejected.
- The owner can read the integrity-checked revision history. Historical revisions are immutable. A schema change requires a new revision and never silently reinterprets prior values. When a draft's stored schema differs from the active schema, API and browser projections hide the old values, identify the mismatch, and require re-entry under the active schema.
- Reads, idempotent retries, and new writes verify each stored command, payload, revision link, and receipt digest across the full offer history; damaged chains fail closed without returning stored values.

## Security and state

- New drafts are private and unpublished. The published flag is always false in this lifecycle. A newly generated form reference is not persisted until its first valid save; canceling before save leaves no ledger record.
- An opt-in owner-scoped Bearer API and authenticated household browser form use the same ledger. The API exposes a summary-only list per household and a read-only owner-scoped revision history; list projections omit form values and producer identity, and history hides values from prior schema versions. The browser form enforces Origin and CSRF; the API write requires Bearer authentication.
- Injected owner authority is checked on every read and write. Validation errors originate from schema rules and do not echo submitted values.
- The current surplus publication-readiness gate remains a separate, read-only evaluation. It must bind to the exact current offer revision and payload digest.
- Local/test persistence is not a production-storage approval.

## Verification

Tests cover owner isolation, role enforcement, injected-schema validation, stale revision conflicts, immutable history, schema-version binding, idempotent retry, conflicting replay, tampered-chain fail-closed behavior, schema-drift value hiding and re-entry, summary-list redaction and owner isolation, revision-history integrity, schema-drift redaction in API/UI history, unsaved-form cancellation, safe Persian rendering, browser CSRF/Origin, cookie-only API write rejection, and the invariant that no draft transition publishes an offer.