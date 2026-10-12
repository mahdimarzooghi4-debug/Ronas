# Ronas — synthetic Business evidence reference handoff (LOCAL/TEST)

**Status:** Technical contract and append-only reference **metadata** only.
This is NOT real evidence collection, legal provenance authentication,
source-rights verification, reviewer qualification, official Business gate
review, or a gate decision. DRAFT PR #9, 2026-10-10.

## Why a separate bounded context

The pre-existing `SqliteSyntheticHumanReviewLedger` owns technical
reviews of immutable **case** fixtures, not Business gate evidence.
The `SqliteSyntheticGateEvidenceHandoff` instead refers exclusively to
the 19 frozen Business requirements indexed in
`business_gate_evidence.py` (D1-B-01..06 / E0-B-01..06 /
FIN-001..007), using the pinned Business PR #1 commit
`5492690e91955e64353824ffa4ec3250286fdf68` and verified source
Git blobs. There are **no** foreign keys, automatic cross-context
propagations or transitions of the Domestic/Export case/grant ledger,
Business gate, financial ledger or source-rights state.

## Canonical local technical lifecycle

Only three technical *presentation* states exist:

1. `NO_REFERENCE`: no synthetic reference for that source requirement
2. `REFERENCE_RECORDED`: a permitted operator submitted a DEMO reference
   ID with an externally **claimed** lowercase SHA-256. The hash does
   not mean the source bytes were fetched or verified. The record is not
   a receipt for real content, consent, chain of custody or rights.
3. `HUMAN_NOTE_RECORDED`: a second independently authorized synthetic
   actor recorded only a DEMO note-reference linked to the same exact
   reference and claimed digest. The note is not exposed or interpreted
   by the system and does NOT verify the evidence or approve the gate.

A case may not loop, change its reference in place, or acquire more than
one technical note under this intentionally limited foundation. No
automatic review assignment, rule, scoring, legal threshold, evidence
quality judgment, approval or rejection is defined.

Both internal commands demand:

- a **trusted, already signed Keycloak-verified** `Principal` with
  the correct independent domain role (`domestic_ops`, `export_ops`,
  or `finance`); Python direct callers must themselves enforce that
  prerequisite, as methods do NOT parse JWTs
- an exact requirement ID present in the pinned 19-item source dossier
- an uppercase `DEMO-...` action and reference ID; a 64-character
  lowercase hexadecimal **claim** about an external document digest
- an exact expected technical revision; action IDs bind immutable actor,
  domain, evidence item, stage, reference, claim digest, note and
  revision, with only *identical* authorized replays returning prior
  results
- for the note only: a separately supplied
  `trusted_review_authorizer(actor, domain, evidence_id)`, with
  **different maker and reviewer**; replay cannot bypass subsequently
  withdrawn reviewer authority

There is no fallback implicit approval role, no seeded real reviewer,
no assumed source rights and no inference that a claim matched bytes.

## Durability and read boundaries

The explicit local SQLite adapter uses private-owner file permissions,
WAL/FULL durability, `BEGIN IMMEDIATE` serialization, append-only
DB triggers, immutable action IDs, monotonically linked sequence and
SHA-256 event chain, plus a stored verified head. On reopen/read/write,
the entire event lineage is revalidated, along with the pinned Business
source-file identity. Corrupted payload, revision, actor linkage,
hash or head fails closed; failed insert rolls back the full command.
It is **not** a tamper-proof externally anchored log against a privileged
actor who rewrites every local row and event digest. SQLite here is
reference/test storage, not a Production database decision.

Only explicitly injected opt-in Keycloak BFF instances mount:

`GET /api/v1/admin/gate-evidence/{domain}/technical-handoff`

This returns one of the 19 **technical** states per scoped evidence ID,
alongside only `gate_status_at_source=OPEN`,
`snapshot_state=PINNED_DRAFT_SNAPSHOT_NOT_LIVE`, pinned source SHA,
`evidence_verified=false`, `rights_verified=false`,
`business_approval=false`, and revision. It **never** returns maker/
reviewer identifiers, receipt IDs, claimed SHA-256, note references,
private document content or Business decision records. Unknown and
unassigned domains return 404. The existing admin HTML gate evidence
detail can optionally display the same technical stage, still without
separate panels, file content, or approval verbs. An invalid signed
JWT/browser session fails authentication; source drift returns
sanitized 503, likewise a corrupt local handoff ledger. No public POST,
PATCH, file-upload, approve/reject or gate-promotion endpoints are
introduced.

The default app does not mount the handoff. Actual source files, consent,
license rights, review authority, any real author appointment and
data-retention contract must be established outside this LOCAL/TEST
foundation **before** any real evidence ingestion can be considered.

## Verification and governance

`backend/tests/test_gate_evidence_handoff.py`: **19 automated
regressions** for empty state, reference and independent note,
reopen, exact idempotency, currently revoked independent reviewer,
maker/checker separation even under permissive authorization, 19-ID
allowlist/domain separation, invalid refs/digests/revisions, audit
tampering/head corruption, insert rollback, parallel idempotent
submission, signed read-only API, UI and session logout, source drift,
malformed revision, default-off and zero Business gate effects.

No Production migration, real authority, rights/source intake, financial
model, allocation, transaction or real human review is established.
Current Business #2 Domestic, #3 Export and #4 Finance are OPEN and
require explicit, authorized **separate** review; PR #1/#9 remain
Draft/Open/Unmerged. Stage/QA/Release/Production have not been authorized.
