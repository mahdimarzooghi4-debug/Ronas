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

## Owner-facing technical progress and detail in the existing user shell (2026-10-10)

This additional **LOCAL/TEST-only** capability shows a household only
minimal observed **technical** progress on its exact immutable Domestic
DEMO record. It is neither a Business milestone, approval, expert opinion,
agronomic assessment nor right to operate; it never sets case status or
consent. It reuses the existing canonical technical state vocabulary:
`UNREQUESTED`, `EVIDENCE_REVIEW_REQUESTED`,
`HUMAN_RESPONSE_RECORDED`. Even the last state means *only* that a
synthetic reference to an independently authorized human response was
recorded, not that the response accepted the household or cultivation plan.

The opt-in review-aware `SqliteSyntheticHumanReviewLedger` adds
`read_owned_domestic_status(ref, principal)`. The caller MUST provide a
Keycloak-verified principal: the method does not verify JWTs itself.
The same `BEGIN IMMEDIATE` transaction validates all grant/review/audit
history, checks exact Domestic `owner_subject` against the signed subject
plus `household` role, derives technical state from durable review steps
and appends a hash-linked `READ_ALLOWED` or `READ_DENIED` audit event
(`HOUSEHOLD_TECHNICAL_STATUS`) for existing DEMO cases. Unknown and
unauthorized cases return the same `None` and HTTP 404. Audit failure
rejects the entire read without a partial response.

The response is the existing immutable `ScopedDraft.public_view()`
envelope plus only `review_revision` and
`technical_review_state`. It does NOT include any request/evidence/
decision reference, reviewer/actor identity, command digest, internal
audit sequence or human note text. Every case still has
`status=DRAFT_ONLY`, `purpose_consent_verified=false`,
`expert_approved=false`, `plan_accepted=false`, `real_data=false`.

The optional GET-only
`/api/v1/domestic/household-intake/my-drafts/{ref}/technical-status`
is mounted with an explicitly injected, review-aware local ledger and
KeycloakConfig; a plain in-memory or base grant ledger cannot expose
review details. JWT absence/invalidity returns 401; another household,
staff-only actor, wrong engine or unknown ID returns indistinguishable
404; corrupt review/audit or SQLite failure returns sanitized 503.
There is no POST or approval endpoint. A reviewer/operator grant
revocation does not modify independent household ownership.

When the already-approved **shared user/partner shell** is explicitly
created with a valid `BrowserOIDC` and the **same exact** review ledger
as its scoped registry, household list links lead to
`GET /my-drafts/{ref}`, a server-rendered owner-only detail page **in
that same shell**, showing synthetic case ID/version, `DRAFT_ONLY`,
current observed technical state and a conspicuous non-approval notice.
Only known safe state labels are rendered; record IDs are HTML-escaped.
A missing/revoked browser session returns 401 and an unauthorized
record returns 404 without exposing its details. No third panel or
unreviewed Business flow was introduced. With a base ledger or absent
review injection, the existing owner list simply retains its
already-authorized minimal JSON detail link, and the new HTML route is
not mounted. The default runtime mounts neither.

13 focused offline regression tests in
`backend/tests/test_owned_household_technical_status.py` cover all
three states, exact owner/engine/role partitioning, no private evidence
or identity leakage, corruption/failed audit, invalid tokens, staff
grant revocation independence, default-disabled behavior, BFF detail
and signed-session logout, plus concurrent owner status read and review
response serialization. This is evidence for a single-host synthetic
development candidate only. Actual case identity, lawful consent,
real agronomist qualification, accessible final user wording, retention
policy and production storage must be approved separately; Domestic
Gate #2, Export Gate #3, Finance Gate #4 remain OPEN.

## One-snapshot household technical progress list (2026-10-10)

The previous owner-only `my-drafts` GET and exact-case owner status detail
are retained. When an operator explicitly injects the **same** local
`SqliteSyntheticHumanReviewLedger` as scoped grant and review source, a new
GET-only `/api/v1/domestic/household-intake/my-drafts/technical-progress`
projects each **owned** Domestic DEMO case's immutable public envelope,
review revision, and current observed technical review state in one page.
A plain `SqliteSyntheticGrantLedger` or default app does not mount this
enhanced endpoint and cannot fabricate a technical-review state.

`list_owned_domestic_progress()` verifies the grant, audit and technical
review ledger, compares each case's immutable owner to the already
Keycloak-verified `household` subject, derives review state from its exact
durable steps, and appends one `READ_ALLOWED` event per returned row with
access mode `HOUSEHOLD_PROGRESS_WORKLIST`. This all happens in **one**
`BEGIN IMMEDIATE` transaction. A concurrent review response therefore
appears in the full page's same audit-ordered snapshot or in the next page
read; the page never mixes independently observed state from separate
per-record reads. Audit append failure aborts the whole page and no partial
case content is returned. The read-only route requires signed Keycloak
authentication (401 if absent/invalid), validates keyset cursor and page
size (422 if invalid), and returns sanitized 503 for corrupt history or
SQLite failure.

Sorting and pagination use `after_ref` and a purely technical 1–50
page-size limit (default 20) **over owned Domestic fixtures only**.
There is no global/unowned count, other household ID, export case,
reviewer identity, internal request/evidence/response reference or
audit digest. Every returned case remains `DRAFT_ONLY` with all existing
unverified consent and agronomy flags. `HUMAN_RESPONSE_RECORDED` remains
merely a reference to a technical response, **not** approval. A staff
grant revocation does not change unrelated household ownership; a
revoked browser session cannot disclose this list. Empty pages have no
per-item read-audit event and do not prove that other owners have no
cases.

In the **same existing** shared user/partner `/` shell, a valid
Keycloak-authenticated household now sees its cases and observed
technical-review progress **on the same list page**, with a clear
Persian non-approval label and links to the existing exact-owner detail.
The UI calls the new one-snapshot ledger facade server-side, without
client-held access token, additional frontend API rounds or new panel.
The base ledger and plain in-memory catalogue retain their historical
read-only listing behavior; review/owner integration remains opt-in only
and disabled in the default runtime. CSP/no-store and HTML escaping
remain enforced. No new login, intake, editing, evidence collection,
AI inference, export approval, finance or real Business workflow exists.

`backend/tests/test_household_progress_worklist.py` contains **14**
offline tests covering authorized keyset pages, observed review updates,
no private evidence, cross-owner/engine isolation, role and signed
identity denial, invalid cursor, corrupt history, audit rollback,
default-off and base-ledger behavior, existing shared user HTML,
browser logout, independent staff-grant revocation, read/response
concurrency ordering and fail-closed HTML. This is synthetic local
single-host evidence only: no real identities, consent, lawful source
rights, runtime distributed transaction or Production approval. Domestic
#2, Export #3 and Finance #4 Business gates remain OPEN.

## Subsequent authoritative decisions still required

Source of record ownership and grant/revocation authority, tenant and delegated
access, audit lineage, actual consent/data/retention/correction rights, qualified
agronomy expert and validated AI plan proposal, export source licensing and
reviewer identity are undefined or not evidenced. None may be invented by a
test fixture or presumed from user approval to develop code. No production
database, money/market/shipping operation, or real user intake is implemented.
Domestic #2 / Export #3 / Finance #4 gates OPEN. PR #1/#9 Draft/Open/Unmerged;
no Stage, Release or Production. No hosting purchase required for this slice.
