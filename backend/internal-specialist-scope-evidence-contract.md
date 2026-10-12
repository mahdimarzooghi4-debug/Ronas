# Ronas — versioned specialist evidence, declared case scope and conflict (LOCAL/TEST)

**Status:** draft unapproved technical foundation for D1-SCI-01 / D1-REV-01..04 and RON-DEC-015..021/033. No scientific professional licensing, real competence assessment, real conflict-of-interest clearance, legally valid appointment or independent review decision exists.

The existing workspace requires **both** a signed Keycloak `agronomy_expert` role and an exact, live, independently checked case assignment before any read or technical missing-evidence question. This access does **not** imply professional qualification or permission to decide an individual programme. The new `SyntheticSpecialistEvidenceRegistry` is a separate, immutable LOCAL/TEST *evidence-candidate* contract; it is NEVER a grant authority. Supplying a candidate must not loosen, replace or bypass the existing live role/case check.

## Distinct immutable candidate evidence

`SpecialistScopeEvidenceCandidate` pins an exact synthetic specialist subject, DOMESTIC case ref/version, sequential evidence revision, a canonical subset of the **three already-defined review tracks**, and *independent* DEMO refs plus SHA-256-shaped fingerprints for:
- the proposed specialist's professional qualification **evidence** (not verified),
- case-specific appointment/scope **evidence** (not an actual valid appointment),
- conflict declaration **evidence** (not independent clearance).

`conflict_declaration_state` is exclusively `CONFLICT_NOT_ASSESSED` or `POTENTIAL_CONFLICT_DECLARED`. **Absence of a declaration does NOT mean no conflict.** Even with all three pointers present or an explicit declared track scope, `qualified_for_track_verified=false`, `appointment_authority_verified=false`, `conflict_independently_cleared=false`, `scope_authorized_for_real_review=false`, and `may_decide_cultivation_plan=false`. No credential type, speciality classification, legal practice criterion, risk score or automatic conflict test is invented.

`SpecialistScopeEvidenceEvent` supports only `SPECIALIST_EVIDENCE_CANDIDATE_RECORDED_UNVERIFIED` and `SPECIALIST_EVIDENCE_CANDIDATE_WITHHELD`. Histories are immutable and versioned *per specialist/case*, exact case version remains pinned, event IDs must be unique, and old versions are never rewritten. Withholding requires a synthetic reason and removes the scope candidate from the **current** diagnostic projection; reintroduction requires a new explicit version, not silent reuse of history. No HTTP write, appointment grant or professional-review mutation exists.

## API and boundary

Optional LOCAL/TEST `trusted_specialist_governance_snapshot` callback returns an immutable registry, independently of Keycloak and the case ledger. An unavailable/malformed callback fails closed (sanitized 503), **after** the normal signed-role/live-assignment check. Without a callback the result explicitly says `NO_SYNTHETIC_EVIDENCE_CANDIDATE`. A wrong case version cannot borrow an older credential/appointment candidate.

A specialist with existing valid case access can call only:

`GET /api/v1/agronomy/assigned-drafts/{ref}/specialist-scope-evidence`

The response contains *only* the requested case ref/version, current candidate revision, broad evidence state, disclosed potential-conflict marker, and three track-level candidate declaration indicators. It never exposes professional document references, identity documents, conflict text, document digests, or the source expert subject. Each successful read verifies the existing append-only shared ledger and appends one `READ_ALLOWED` event in the **same** transaction. No POST/PATCH/DELETE exists. Unauthenticated 401; role/case mismatch or live assignment revoked 404; invalid/unavailable independent source 503.

The in-memory history fingerprint is a **structural SHA-256 only**, not signed attestation or a credential. Registered candidates do not affect `_allowed`, existing question mutations or any of the three expert review axes. There is no grant/evaluation model; **actual credential verification, independent conflict resolution, legal appointment and auditable decision authority remain separately required**.

LOCAL/TEST only; unapproved Business candidates; Domestic #2 / Export #3 / Finance #4 OPEN; PR #1 and #9 remain Draft/Open/Unmerged; no Ready for Review, Merge, Stage, QA Gate, Release, Production.
