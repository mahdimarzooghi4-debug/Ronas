# Ronas — Synthetic record-level authorization (D1-A / E0-A)

Status: **isolated Technical/test contract, NOT operational records, an approved
business data policy, or Production storage**. 2026-10-10.

## Invariant: signed role is necessary, not sufficient

A Keycloak-signed Domestic or Export role cannot read all cases. The backend
must also match an explicit trusted-server assignment to the **exact case**
and actor identity. The user-facing household owner must match the signed
subject. The shared admin shell does not imply shared access to data.

The new scoped_drafts.py module supplies immutable synthetic objects:

- ScopedDraft: fixed DEMO-* ID, DOMESTIC or EXPORT engine, synthetic-* owner,
  immutable positive version, exact role/subject grant tuples. Export requires
  a synthetic DEMO-* source reference, not licensed market content.
- ScopedGrant: explicit trusted-server fixture only; never accepted via HTTP.
  Domestic grants accept domestic_ops only; Export grants export_ops only.
- ScopedSyntheticDraftRegistry: immutable tuple-to-record lookup and minimal
  response DTOs. The status is always DRAFT_ONLY, with source SYNTHETIC_ONLY,
  and all consent/expert/source-rights/buyer/contract approval flags false.

## Explicitly injected read-only routes

| Route | Required access beyond signed Keycloak token |
| --- | --- |
| GET /api/v1/domestic/household-intake/drafts/{ref} | household role AND exact owner subject |
| GET /api/v1/admin/domestic/household-intake/drafts/{ref} | domestic_ops role AND matching case grant |
| GET /api/v1/admin/export/research/drafts/{ref} | export_ops role AND matching case grant |

Unauthorized/wrong-engine/missing cases all return 404 DRAFT_NOT_FOUND,
rather than an existence oracle. Missing/invalid identity returns 401.
Query params, browser state, X-Role/X-Case-Grant and user-controlled version
cannot create a trusted assignment. Governance and Finance have no implicit
case access, even alongside other roles. The caller cannot POST or amend
record grants, consent, plan, research reviews or financial states.

The app **does not mount** these endpoints unless an explicitly trusted
ScopedSyntheticDraftRegistry is injected into create_app with KeycloakConfig.
The default runtime leaves this surface unavailable and processes no real
records. The pre-existing static UI and BFF synthetic shell remain separate.

## Tested evidence

tests/test_scoped_drafts.py covers owner isolation, cross-household attempts,
case-specific Domestic/Export assignment, mixed-role escalation, cross-engine
lookup, query/header spoofing, denial parity, missing/invalid signed bearer,
immutable case lineage, synthetic-only envelopes and a cookie-authenticated
BFF case-read test. The existing API/Keycloak tests remain intact.

At initial implementation SHA 379e5c48b8900314524cdea04a1d0acc6bb481f0:
- Push CI https://github.com/mahdimarzooghi4-debug/Ronas/actions/runs/38052687458
- PR CI https://github.com/mahdimarzooghi4-debug/Ronas/actions/runs/38052690501

Both SUCCESS: 83 backend Python + 31 prototype Python + 10 Node = 124 tests,
plus Python compilation and dependency validation. This is not a real data,
live Keycloak, distributed grant-revocation or penetration test.

## Owned household draft list and existing shared user shell (2026-10-10)

The optional LOCAL/TEST `SqliteSyntheticGrantLedger.list_owned_domestic_drafts()`
extends exact-owner read permission into an immutable, bounded **list**. It
requires an independently signed and verified `household` role **and**
`principal.subject == ScopedDraft.owner_subject` for *each* displayed
Domestic record. It never derives ownership from the session cookie value,
JWT role alone, grant to `domestic_ops`, a query-supplied subject, or any
client-provided claim. Export records never enter this household listing,
even when the same synthetic actor is seeded as their owner.

A deterministic keyset `after_ref` cursor and technical `limit` (1–50,
default 20) operate over **authorized owned Domestic records only**.
Page-size bounds are technical response protection, not eligibility,
consent or Business thresholds. No global case counts, other households'
identifiers, unknown-case counts, or owner-subject values are returned.
Results contain only the previously established `ScopedDraft.public_view()`
fixture: `DRAFT_ONLY`, `SYNTHETIC_ONLY` and explicit unverified
consent/agronomy flags. No case creation, editing, approval, or grant
mutation is available.

An entire page is checked and audited under the existing SQLite
`BEGIN IMMEDIATE` transaction, appending a hash-linked `READ_ALLOWED`
event with access mode `HOUSEHOLD_OWNED_WORKLIST` **for each disclosed
case**. Audit insertion failure rolls back the page, and corruption
fails closed without returning any case content. An unassigned or
wrong-role actor obtains an empty list without disclosing any other owner.
A separate operator grant revocation does not revoke the household owner's
independent self-access; it does not create or restore an operator grant.

The GET-only `/api/v1/domestic/household-intake/my-drafts` is mounted
only when a KeycloakConfig and explicit opt-in
`SqliteSyntheticGrantLedger` (or its review-aware subclass) are provided
to `create_app`. A plain in-memory ScopedSyntheticDraftRegistry
does not mount the list, and default runtime mounts no such route.
Unsigned/invalid token returns 401; invalid cursor/limit 422; SQLite
audit/integrity failure 503. There is no POST route.

With the same explicitly injected ledger and a validated BrowserOIDC
session, the **existing shared user/partner `/` shell** renders the
`پرونده‌های من` section for household role only. Rows link to the already
owner-authorized GET `/api/v1/domestic/household-intake/drafts/{ref}`.
Only their own DEMO refs appear, safely HTML-escaped; other user/partner
roles remain unchanged. The previous fixed illustration is suppressed
when the live synthetic owner list is explicitly supplied, even when that
household owns zero cases. No new user portal or external registration,
actual identity, real consent, agronomist qualification or transaction
is implied. A revoked or expired browser session cannot display the list.
CSP and no-store headers remain intact.

`backend/tests/test_owned_household_drafts.py` includes 15 offline
integration/security scenarios covering signed owner segregation, exact
pagination, wrong role, signed-token denial, operator revocation
independence, append rollback and corrupted history, opt-in defaults,
shared HTML and logout, and concurrent list/revocation ordering. The
tests use synthetic immutable records and locally generated signing keys.
These are not Production privacy, legal access or distributed-storage
approvals; Business gates #2/#3/#4 remain OPEN.

## Subsequent authoritative decisions still required

Source of record ownership and grant/revocation authority, tenant and delegated
access, audit lineage, actual consent/data/retention/correction rights, qualified
agronomy expert and validated AI plan proposal, export source licensing and
reviewer identity are undefined or not evidenced. None may be invented by a
test fixture or presumed from user approval to develop code. No production
database, money/market/shipping operation, or real user intake is implemented.
Domestic #2 / Export #3 / Finance #4 gates OPEN. PR #1/#9 Draft/Open/Unmerged;
no Stage, Release or Production. No hosting purchase required for this slice.
