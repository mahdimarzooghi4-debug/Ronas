# Ronas — Synthetic human-review evidence and decision-reference history

Status: isolated, opt-in, LOCAL/TEST technical candidate (2026-10-10).
Domestic Gate #2, Export Gate #3 and Finance Gate #4 are OPEN.

## No business approval or real case state changes

The only technical states are UNREQUESTED -> EVIDENCE_REVIEW_REQUESTED ->
HUMAN_RESPONSE_RECORDED. The underlying ScopedDraft remains DRAFT_ONLY
at every stage. A recorded synthetic human-note reference is NOT an
approved cultivation plan, scientific recommendation, source-rights
clearance, verified exporter/buyer, actual human signature or contract.
No approval/rejection category, threshold, retention period or
decision-making authority is invented.

## Internal command and verification boundary

Module: ronas_api/human_review_sqlite.py.
Requesting review requires an injected, preverified Keycloak principal,
a current exact-record, exact-engine operations grant, immutable case
version, expected technical-review revision zero and synthetic request
and evidence references. Recording a human response requires the exact
same request reference, revision one, current case version and a distinct
assigned actor additionally accepted by an independently injected human
review authorizer. An ordinary governance/finance role cannot bypass it.
Revoked grants cannot create or complete a review. Neither method has
an HTTP endpoint. No AI, data ingestion, consent or real decision is run.

Both stages are append-only SQLite rows accepted atomically with a linked
audit event in one BEGIN IMMEDIATE transaction; read-only history and
review-state queries validate exact case, stage, actor digests, evidence,
decision reference, command payload hash and audit chain. Identical
actions replay idempotently; changed replay, stale version, missing
request, same-actor response and concurrent conflicting requests fail
closed. Evidence/request/note refs are DEMO-only identifiers, not actual
content, reviewed facts or access rights. A non-review-aware generic
grant ledger refuses to open an audit history with review-specific
events rather than silently ignoring them.

## Currently authorized read facade (internal only)

`read_review_for_operator(engine, ref, principal)` is the opt-in
technical-history read boundary. The caller must already have validated the
Keycloak signature, issuer, audience and client role; a bare Python `Principal`
is **not** proof of signature verification. The ledger checks a current
exact-case and exact-engine operations assignment in the same
`BEGIN IMMEDIATE` transaction as the read and audit append. A previously
valid JWT does not bypass a revoked case grant. Governance, finance,
unassigned and cross-engine actors cannot read technical evidence references.
Unknown case and unauthorized case return the same `None` result.

For a known synthetic record and syntactically valid synthetic subject, each
read attempt appends `READ_ALLOWED` or `READ_DENIED` with the existing
hash-chained audit vocabulary and `TECHNICAL_REVIEW_HISTORY` access mode.
A failed audit insert aborts the entire read, without returning its contents.
Concurrent revocation and read are serialized by SQLite's transaction lock;
a successful read must precede revocation in the audit sequence. Authorized
results contain only engine/ref, case version, immutable `DRAFT_ONLY` status,
technical state/revision and a sequence of DEMO stage, request, evidence,
note and audit-sequence references. They omit actor and command digests,
actual note contents, identity and new approval/denial categories.

`review_state` and `review_history` remain **trusted internal diagnostic
helpers**, without authorization checks. They MUST NOT be exposed through an
HTTP route, used as a session-facing interface or interpreted as an
operational review decision. Downstream UI/BFF integrations must use an
authenticated, exact-case-checked facade and must not trust a client-
supplied `Principal`. Only the explicitly opted-in read-only technical API and the assigned worklist described below may be mounted. This is
not a Production read/authorization policy and no new user role is granted.

## Opt-in signed-Keycloak HTTP read boundary (LOCAL/TEST ONLY)

`backend/ronas_api/technical_review_api.py` provides two **GET-only**
technical evidence-reference views, each inside the one unified admin
environment and isolated by engine:

- `GET /api/v1/admin/domestic/household-intake/drafts/{ref}/technical-review`
- `GET /api/v1/admin/export/research/drafts/{ref}/technical-review`

The default `app = create_app(KeycloakConfig.from_environment())` does **not**
mount them. Even passing a `scoped_registry` alone does not mount them. Local
offline tests must explicitly construct an `SqliteSyntheticHumanReviewLedger`
and pass that exact same object as **both** `scoped_registry` and
`technical_review_ledger` to `create_app(KeycloakConfig, ...)`. A
generic OIDC verifier, missing ledger or differing grant catalogue is rejected
at application construction. Neither handler accepts an actor/role from
query parameters, request body or client headers. Authentication uses the
app's existing signed Keycloak client-token verifier (or an independently
validated browser flow bound to that Keycloak configuration), followed by
the ledger's exact-case current grant check and a transactional read audit.

Response semantics: `401` for missing/bad JWT; identical `404
DRAFT_NOT_FOUND` for absent, unassigned, cross-engine or revoked cases;
`503 TECHNICAL_REVIEW_UNAVAILABLE` for verified audit corruption or
SQLite failure (no untrusted references in the HTTP response). Authorized
reads return a bounded DEMO-only history without actor/command digests or
real note text. `Cache-Control: no-store` is applied globally. No POST,
workflow decision, consent mutation, external supplier verification or
Business state transition is exposed, and no new portal is created.

Existing `review_state()` and `review_history()` are INTERNAL
diagnostics and MUST NOT be used in an HTTP handler. Keycloak client
role verification alone cannot authorize history reads. The allowed
technical state `HUMAN_RESPONSE_RECORDED` is explicitly **not** a
Business approval. These routes do not form a Production API contract.

## Encrypted browser session and immediate-revocation test contract

An opt-in browser client uses the same existing Keycloak Authorization Code +
PKCE callback and independently verified ID/access-token subject, followed by
an encrypted, local SQLite session record. The browser owns only an opaque
`__Host-ronas_session` cookie (Secure, HttpOnly, SameSite=Lax); it never receives
a JWT in the technical-review response. Every review GET revalidates the
stored signed access token's current expiration, issuer, API audience and
client role via `BrowserOIDC.session()`; the session's own expiration and
revocation are also enforced. A malformed or expired cookie, invalid
signature/claims, stale stored role/subject, or revoked session produces
`401` **before** a review-ledger access audit. An explicitly malformed
Authorization Bearer header cannot silently fall back to a valid cookie.

A still-active, signed browser session is not sufficient to read a
synthetic case: the review ledger checks current exact-case grant status
on **every GET** and writes a transactional audit event. Thus an independent
grant revocation returns `404` on the very next read even if the session is
otherwise valid. Successful logout with matching Origin and session CSRF
revokes the opaque SID across separate SQLite connections; failed logout
with incorrect Origin or CSRF must not revoke it. GET has no approval
action, while POST is not supported.

Evidence: `backend/tests/test_technical_review_browser_security.py` runs
11 offline integrated scenarios using ephemeral local RSA and AES keys,
the real PKCE callback code paths, two independent SQLite session-store
objects and the same synthetic review ledger. These prove the **local code
contract**, not a deployed Keycloak identity service, independently
qualified reviewer, external revocation feed, browser penetration assessment,
production multi-node store, or any Business case approval. No real data,
consent, source-rights or financial transactions are activated.

## Three-boundary interleaving and restart verification (2026-10-10)

The optional browser cookie, synthetic exact-case grant, and technical-review
history have three distinct trust boundaries. A current signed access-token
subject/role and valid encrypted local BFF session are necessary, but do NOT
substitute for a current exact-engine, exact-record operations grant in the
review-ledger SQLite database. A recorded technical human-response reference
does not authorize any Business case transition; all cases remain
`DRAFT_ONLY`.

Regression fixture: `backend/tests/test_session_grant_review_interleavings.py`
adds seven synthetic local tests using a pinned locally generated Keycloak
public JWKS, separately reopened encrypted browser-session store connections
and independently reopened review-ledger connections. The tests verify:

- A successful logout invalidates the SID on either connection, returning
  401 before further review-ledger read/audit events
- A valid unrevoked browser session loses exact-case review access with 404
  after a separately committed grant revocation; cross-engine access does
  not appear
- Request-versus-revocation and independently authorized
  response-versus-revocation are linearly ordered by the **single review
  ledger's** `BEGIN IMMEDIATE` transaction: a successful review event
  precedes revocation in the audit, or it never commits
- A replay of the exact same request after grant revocation cannot
  re-enable the requester or mutate previously accepted review lineage
- Corrupt local technical evidence fails closed with 503 through both
  the still-valid browser session and a correctly signed Bearer token
- Reopening both stores after logout and exact-case revocation cannot
  resurrect the old session or the revoked grant; a new synthetic session
  for the same signed actor remains denied that case

**Important concurrency limitation:** session logout and case-grant
revocation operate in **different SQLite databases** and are not one atomic
distributed transaction. Requests already authenticated/in flight can
complete before a competing logout commits. Likewise an already accepted
review/read can precede a competing case-grant revoke. The documented
postcondition is denial for new reads **after** the relevant revocation has
committed, not retroactive cancellation or a cross-database linearization
point. The tests assert the causal audit order only *inside* the one
review-ledger transaction and never pretend the session store and grant
ledger are transactionally coupled.

These are deterministic local-contract exercises with only synthetic
subjects, reference IDs and self-generated signing/encryption keys. No
real Keycloak provider, operational distributed store, cross-host
consistency, lawful Domestic consent, Export source rights, qualified
human-review authority, real Business approval, Stage or Production is
represented by the result.

## Assigned operator technical-review worklist (LOCAL/TEST only)

This is a new read-only **technical** capability for the existing unified
admin environment, **not** a Domain Business work assignment, cultivation
approval queue, export source-rights adjudication, or separate staff panel.

The opt-in `SqliteSyntheticHumanReviewLedger.list_technical_review_worklist()`
lists only currently assigned, unrevoked DEMO cases for a previously
Keycloak-verified operator. Its exact signed API client role and active
per-case/per-engine grant must both be present. Cases are sorted by their
immutable synthetic `ref`, and keyset pagination uses an optional
`after_ref` and a technical resource safety bound of 1–50 records
(default 20). These numbers limit response size only; they are **not**
eligibility, Business or model thresholds. `next_cursor` is set only
when there are more *authorized* cases after the page. No global counts,
other users' case names, ownership identifiers, request/evidence/note
references or even the number of excluded cases are returned.

Only immutable `ref`, engine, version, `case_status=DRAFT_ONLY`,
`review_revision` and the observed **technical** review state are
returned. `HUMAN_RESPONSE_RECORDED` is not approval. One
`BEGIN IMMEDIATE` transaction verifies the entire ledger, checks the
current grants and appends a `READ_ALLOWED` audit event with
`TECHNICAL_REVIEW_WORKLIST` access mode for each item included in that
page. A failed append aborts the whole page. Invalid, unassigned or
revoked grants are never disclosed and do not generate item-level audit
events. Empty lists do not imply absence of other cases.

Two GET-only endpoints are added to the existing explicitly opted-in
technical-review router:

- `GET /api/v1/admin/domestic/household-intake/technical-review-worklist`
- `GET /api/v1/admin/export/research/technical-review-worklist`

`limit` and `after_ref` are read-only query controls. Unauthenticated
or invalidly signed requests fail 401; malformed cursor or limit returns
422; unassigned operators with verified role receive an empty list
(no existence oracle), and ledger-integrity failure returns sanitized
503 without partial results. Both engines have separate URLs and
per-case grants; a dual-role user cannot inherit case permission from
the other engine.

**Existing admin HTML integration:** when `create_app` is supplied a
Keycloak-validated `BrowserOIDC` and the **same explicit** synthetic
human-review ledger as its scoped-case registry, the server-side
`/admin` view shows only that signed session holder's granted
technical-review worklist in their existing Domestic and/or Export
management domain. Rows link to the already-existing authorized
technical-history GET. Next-page links use a synthetic keyset cursor.
HTML is escaped, and headers remain `Cache-Control: no-store` and
CSP `frame-ancestors 'none'`. Finance and governance roles do not
inherit case listings; session logout or a grant revoke stops subsequent
disclosure. An invalid audit produces a sanitized 503 without partially
rendered cards. No new panel, user login path, public registration,
write/approve endpoint, personal data or automatic decision is created.

The default `app = create_app(KeycloakConfig.from_environment())`
mounts neither the BFF nor any technical-review worklist. A
`scoped_registry` alone still does not activate it. These are only
explicit LOCAL/TEST development candidates; real Keycloak roles and
Business/Technical approval, consent, export rights, session authority,
retention and Production storage are not established.

Validation: `backend/tests/test_technical_review_worklist.py` contains
18 offline HTTP and HTML security/function tests for pagination,
seed/grant filtering, Domestic/Export isolation, live status,
revocation, concurrent reads, corrupted history, transactional audit,
invalid query, default-disabled routes, unified admin rendering,
session revocation and role-specific display. No real IdP or
business execution was used.

## Tests and exclusions

Tests: backend/tests/test_human_review_sqlite.py (27 offline tests).
Scenarios cover restart/reopen, independent authorization, revoked
grant, cross-engine isolation, request binding, forced SQL insert
rollback, audit tampering, SQLite append-only triggers, concurrent
replay/CAS, missing request and absence of public decision endpoints.
Additional scenarios exercise exact-case read authorization, denied-role/assignment/engine access, immediate revocation, atomic audit-write failure and concurrent read/revocation ordering. The separate backend/tests/test_technical_review_api.py suite adds 10 real HTTP admission and denial tests with ephemeral locally signed test JWTs: positive Domestic and Export, response-only reference, invalid claims, role and assignment denial, immediate revocation, corrupted audit, rollback-on-audit-error, default route disabled and mismatched injection blocked. Existing Keycloak and synthetic domain tests remain in the same CI.

This is a local single-host SQLite simulation, NOT a production store,
distributed consistent authorizer, tamper-proof independent audit or
real identity/consent/source-rights acceptance. Business Gate decisions,
genuine agronomy expert qualification, actual human decision rights,
operational workflow definitions, lawful case data, production
infrastructure and human QA/security approval remain open.
PR #1 and #9 stay Draft/Open/Unmerged. No Stage or Production.
