# Ronas — Immutable synthetic scientific source candidate history (LOCAL/TEST)

**Technical DRAFT only.** This is a narrow Ronas-owned foundation for the **unapproved** Business D1-SCI-01 candidate in PR #1 and RON-DEC-014..021/027/028/033. It contains NO real agricultural source text/files, retrieved/authenticated bytes, actual licence, real scientific review, qualified specialist registration, AI Training authorization, plan approval, or Production data.

## Why a candidate history?

The existing `ScientificSourceCandidate` and `ScientificBasisCandidate` pin a set of hypothetical source/content, rights-document and science-review material **pointers**. Until now current sources came only from an injected callback. The new `SyntheticScientificCatalogue` is an **immutable sequence of explicit synthetic source-change events** and a typed current snapshot that can be injected through that existing callback. It does not create a parallel household ledger, public mutable API, or a pretend legal/science authority.

Each `SyntheticSourceCatalogueEvent` is strictly synthetic (`DEMO-` IDs) and has one source-ref, consecutive per-source revision and one of two **technical non-decision** operations:
- `CANDIDATE_VERSION_RECORDED_UNVERIFIED`: carries an existing strictly validated `ScientificSourceCandidate` with exactly the event's source ref/version.
- `CANDIDATE_WITHHELD_FROM_NEW_SYNTHETIC_USE`: requires a DEMO reason pointer, no candidate; excludes the ref from the *current* candidate snapshot without deleting any prior event or source/rights/science pointer.

No event can claim APPROVED, LICENSED, SCIENCE_VALIDATED, AI_TRAINING or actual crop suitability. Same `action_ref` replay, missing revisions, booleans-as-revisions, withholding a missing/already withheld source, or cross-purpose input fail closed. A withheld candidate can be reintroduced only with the next explicit synthetic version and never by silently reviving the old record. Distinct source revision chains remain separate. All source data stays a **structured pointer**, not a content store.

`current_sources()` returns a deterministic typed snapshot for **existing synthetic** `inspect_scientific_basis_structure(...)`; a changed/withheld source version or rights/science material pointer fails closed on dependent historical basis manifests. Unrelated catalogue sources do not invalidate another basis. `snapshot_at(event_ordinal)`, `redacted_summary()`, and `compare(from,to)` provide a replayable versioned history and count-only difference indicators (new, withheld, content pointer changed, service rights-document pointer changed, science-review-material pointer changed, explicit version-only revision). The SHA-256 history fingerprint is canonical and deterministic, not a signature, evidence that bytes exist, or a licence. Output never exposes raw scientific refs, rights docs, source-content hashes, crop advice or model details.

**Architecture boundary:** The events are an immutable *in-memory/test-fixture* contract, **not durable authoritative ingestion**, not multi-process transactional storage and not a source-grant/policy engine. Earlier snapshots are for historical comparison only, never to be injected as a current trusted source authority to bypass stale/withheld candidate detection. The existing specialist case reader still requires signed role, exact live assignment and its independent current-source callback; this package introduces no new business decision or production access endpoint.

Future real registry must separately establish authentic source files/provenance, actual scope-specific service and Training rights, qualified content reviews, withdrawal governance, storage/retention, auditable writer authority and cross-instance consistency, only after explicit Business/Technical decisions.

**Gates:** Domestic #2, Export #3, Finance #4 OPEN. PR #1/#9 remain Draft/Open/Unmerged; no Ready for Review, Merge, Stage, QA Gate, Release or Production. Tests remain LOCAL/TEST.
