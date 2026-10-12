# Ronas — One-transaction Business evidence technical readiness matrix

**Status:** LOCAL/TEST read-only technical projection, dated 2026-10-10.
This is neither a live Business gate, source authority, expert-license
checker, permission to collect a real document, nor a Production plan.

## Purpose

Earlier local technical foundations have three independently governed
records: a synthetic handoff to one of the 19 version-pinned Business
evidence requirements; a technical note reference from an independent
synthetic human reviewer; and one of three technical enquiry tracks
`ORIGIN`, `SOURCE_RIGHTS`, `REVIEWER_QUALIFICATION`. It would be
misleading to assemble a single admin status page with separate requests
that might observe different SQLite commits. The new
`read_readiness_matrix(principal, domain)` returns a **single verified
snapshot** of all permitted requirements for exactly one signed domain.

## Source and transaction

The method is defined on the opt-in
`SqliteSyntheticAuthorityEnquiryLedger` and requires the exact same
injected `SqliteSyntheticGateEvidenceHandoff` as its source of truth.
It performs, in this order:

1. Checks a caller-provided **previously Keycloak-verified** Principal
   for the exact `domestic_ops`, `export_ops`, or `finance` role;
   a `governance` role alone does not grant technical access
2. Attests the two pinned historical Business source Markdown blobs
   and the corresponding evidence ID/status rows
3. Enters one `BEGIN IMMEDIATE` transaction in the existing
   LOCAL/TEST SQLite store
4. Re-validates the complete original handoff event chain, all enquiry
   chains, the source-action digest lineage, and both stored heads
5. Projects each permitted source requirement to its last observed
   `NO_REFERENCE / REFERENCE_RECORDED / HUMAN_NOTE_RECORDED` state and
   all three corresponding
   `NO_REQUEST / CHECK_REFERENCE_REQUESTED /
   TECHNICAL_RESPONSE_REF_RECORDED` states and technical revisions
6. Exposes only conservative preflight blockers with
   `evidence_verified=false`, `admission_allowed=false`,
   `business_gate_passed=false`, and an explicit
   `matrix_state=BLOCKED_EXTERNAL_VERIFICATION`

For concurrent writes against the **same SQLite database**, the page
observes the review response either before or after it commits, never
as a mix of separate per-card reads. It is not a distributed
transaction across real providers or independent systems. The read
**verifies** append-only history but does **not** append its own
read-audit event or prove external audit notarization. Runtime
storage remains LOCAL/TEST, not an approved Production choice.

There are no hidden household/other-domain IDs, grand totals,
request/response references, note text, issuer identities, actor
hashes, claimed document digests or personal information in the
projection. The response deliberately carries the historical source
SHA and `snapshot_state=PINNED_DRAFT_SNAPSHOT_NOT_LIVE`.

## API and existing unified admin shell

This optional GET-only API is mounted **only** with a Keycloak
`BrowserOIDC`, explicitly injected source handoff, and the exact
same explicitly injected authority enquiry object:

`GET /api/v1/admin/gate-evidence/{domain}/readiness-matrix`

An existing signed domain-admin can open
`GET /admin/gate-evidence/{domain}/readiness` in the **same unified
admin shell**, via a link on the permitted source-dossier page.
No new role, panel, user environment, mutation command, file upload,
provider dispatch or approval button is added.

The Governance role can continue reading **public draft Business
gate metadata** for all three domains. It **cannot** thereby read
domain-operator handoff/preflight/enquiry/matrix details; those require
the respective signed domain role. Other unassigned or unknown domains
receive indistinguishable HTTP 404. Invalid credentials/session give
401; corrupted handoff or enquiry history gives sanitized 503 with
no partial disclosure; drifted pinned source files also fail closed.
Responses retain `Cache-Control: no-store` and HTML CSP.

## Validation and external blockers

`backend/tests/test_gate_readiness_matrix.py` adds **15** offline
scenarios: all 19 source requirements in domain-scoped pages; exact
technical stages after request/response; three independent enquiry
streams; signed bearer/cookie and logout; governance-vs-domain
separation; no leak of references/digests; default-off and mismatched
ledger denial; POST rejection; damaged original/enquiry history;
changed pinned Business source; and simultaneous matrix read and
independent human response. All data and signing keys are
ephemeral/synthetic. Successful tests **do not** validate a real
source, actual rights or a qualified human.

Business gates #2 Domestic, #3 Export and #4 Finance remain OPEN in the
pinned draft source. PR #1 and PR #9 must remain Draft/Open/Unmerged.
No Stage, QA Gate, Release, Production or Merge is authorized.
