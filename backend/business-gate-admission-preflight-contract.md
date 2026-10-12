# Ronas — Business Evidence Admission Preflight (LOCAL/TEST ONLY)

**Status:** blocking technical-readiness projection, not admissibility approval.
Created 2026-10-10 on Draft PR #9. It does not accept, evaluate the legal
validity of, store, or retrieve real customer/business evidence. No real
user, reviewer licence, source rights, or provenance authority has been
integrated or invented.

## Purpose and separation of independent questions

For each of the 19 pinned Business evidence identifiers
(D1-B-01..06, E0-B-01..06, FIN-001..007), the technical handoff previously
captured a `DEMO` reference and an **externally claimed** SHA-256,
and optionally an independently authorized synthetic reviewer-note
reference. Those do not constitute verification.

The new preflight distinguishes **four non-interchangeable checks**:

1. **Claimed-byte comparison:** Are *supplied LOCAL/TEST DEMO bytes*
   equal to the digest **claimed by the synthetic submitter**? This
   demonstrates only integrity relative to that claim, **not authenticity,
   custody, provenance, legal rights, quality or suitability**.
2. **Origin authenticity:** Does a trusted, authoritative provider
   establish who produced the actual evidence and its provenance?
   **NOT_AUTHENTICATED**; no source/origin provider has been selected.
3. **Source/consent/license rights:** Do real, legally authorized
   evidence and permissions permit this precise use? **NOT_VERIFIED**.
   Business has not approved rights/consent contracts or authoritative
   verification sources. No status is inferred from a source reference.
4. **Qualified independent reviewer:** Has a permitted authority
   verified the specific human's qualification, mandate and
   current authority for that item? **NOT_VERIFIED**. A signed technical
   domain role, a test authorizer callback or
   `HUMAN_NOTE_RECORDED` never establishes a real reviewer credential.

For all items, the preflight hard-codes the conservative outputs
`evidence_verified=false`, `admission_allowed=false`,
`business_gate_passed=false` and
`preflight_state=BLOCKED_EXTERNAL_VERIFICATION`, regardless of
claimed reference status, SHA-256 comparison result or human-note stage.
Even in the synthetic byte-match scenario, legal rights and
qualification blockers persist. **No path through this module can
transition a Business gate to PASS.**

## Opt-in read model and isolated byte comparison

`backend/ronas_api/gate_evidence_preflight.py` is a pure versioned
projection. The existing append-only
`SqliteSyntheticGateEvidenceHandoff` gains
`preflight_worklist(principal, domain)`; it reuses the
same signed-principal **domain-scoped** and full-history/source-integrity
checks as its original `worklist()`.

With an explicitly injected local handoff ledger and Keycloak browser
integration, the **only new HTTP endpoint** is:

`GET /api/v1/admin/gate-evidence/{domain}/admission-preflight`

Unknown or unassigned domains receive the same 404, invalid/missing
identity 401, and corrupted handoff or source blob 503 with no leaked
references. It does not accept a payload or support POST. The response
contains requirement ID, technical handoff stage/revision and
non-sensitive blocker codes only — no claimed digest, original
reference, rights/qualification claims, reviewer name or note text.
The existing unified `/admin/gate-evidence/{domain}` shows an explicit
Persian "admission blocked" notice when the opt-in handoff is active;
it is not a third UI environment or an approval screen.

**Optional internal offline test helper:**
`inspect_demo_reference_bytes(..., demo_bytes: bytes)` accepts only a
bounded byte string starting with `DEMO-` (1 MiB technical size cap,
not a Business threshold), after exact domain role, evidence ID,
synthetic reference, pinned source, and append-only history checks.
It hashes actual supplied bytes and uses constant-time comparison to
the persisted **claim**. It returns only `DEMO_BYTES_MATCH_CLAIM`
or `DEMO_BYTES_DIFFER_FROM_CLAIM` plus the persistent blockers.
The comparison is **ephemeral** — it never persists an approved status,
changes a stored event, returns bytes/digest, reads remote documents or
attaches an actual proof. The HTTP API does **not** offer byte inspection
or upload; API preflight continues to say `NOT_CHECKED` after a
successful local byte comparison. Do not use this helper with real
documents or personal information.

## Boundaries and future evidence contracts

Before real evidence can ever enter an operational review, Business
owners must explicitly define and approve *authoritative sources*,
purpose/consent/rights scope, reviewer qualification authority,
storage/retention and privacy controls, applicable legal rules and
actual case/gate acceptance criteria. The code must then obtain
real evidence from permitted sources and independently verify exact
artifact lineage, rights and current human reviewer authority.
**There is no automatic promotion even when future evidence is strong.**

No such source, policy, external trusted adapter, reviewer credential,
risk threshold, real document or Production database is established in
this slice. Do not remove these blockers by swapping labels, trusting
unverified UI input, treating digest equality as provenance, or using
the development reviewer callback as real authorization.

Test suite: `backend/tests/test_gate_evidence_preflight.py` contains
14 focused offline regression tests for all three Business domains,
every blocker on NO_REFERENCE/REFERENCE_RECORDED/HUMAN_NOTE_RECORDED,
positive/negative actual DEMO byte matching, no promotion, invalid
types/content/size, wrong domain/actor/ref, denied signed API,
read-only and default-disabled routes, sanitized 503 on corrupt history,
minimal shared admin warning, session logout and strict stage vocabulary.
These tests are synthetic only and do not count as real source-rights
assurance or independent human security review.

Business Gates Domestic #2, Export #3 and Finance #4 remain OPEN at
the pinned DRAFT source. PR #1 and PR #9 remain Draft/Open/Unmerged.
No Stage, QA Gate, Release, Production or merge is authorized.
