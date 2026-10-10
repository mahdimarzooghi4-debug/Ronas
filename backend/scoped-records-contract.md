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

## Subsequent authoritative decisions still required

Source of record ownership and grant/revocation authority, tenant and delegated
access, audit lineage, actual consent/data/retention/correction rights, qualified
agronomy expert and validated AI plan proposal, export source licensing and
reviewer identity are undefined or not evidenced. None may be invented by a
test fixture or presumed from user approval to develop code. No production
database, money/market/shipping operation, or real user intake is implemented.
Domestic #2 / Export #3 / Finance #4 gates OPEN. PR #1/#9 Draft/Open/Unmerged;
no Stage, Release or Production. No hosting purchase required for this slice.
