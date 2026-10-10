# Ronas — External authority connector boundary (disabled foundation)

**Status:** LOCAL/TEST technical contract, 2026-10-10, Draft PR #9.
**No provider, credential, external endpoint, authority, source-use
permission, real evidence dataset, reviewer certificate, verification
policy or response trust root has been selected or admitted.**

## Why this boundary exists

The existing 19-item draft Business evidence registry and append-only
technical ledgers can record synthetic `DEMO-` source references,
independent human-note references and separate technical enquiries
`ORIGIN`, `SOURCE_RIGHTS` and `REVIEWER_QUALIFICATION`. They cannot
verify evidence, rights, or authority merely by recording an enquiry
or its response reference. A future third-party client must not be
implicitly activated by an API credential, a passing unit test, an
existing signed domain role, a digest match or a user-submitted claim.

The new `gate_authority_connector_boundary.py` defines:

- `AuthorityRequestIdentity`: versioned internal, **non-public**
  technical request identity pinned to the exact historical Business
  source commit, source domain and evidence ID, one of the three
  enquiry channels, the original `REFERENCE_RECORDED` action and
  event SHA-256 digest, the exact `CHECK_REFERENCE_REQUESTED` action,
  event SHA-256 digest, DEMO request reference and revision
- `AuthorityRequestIdentity.fingerprint`: deterministic SHA-256
  of canonical serialized identity fields. This is **not** a digital
  signature, authorization token, provider credential, evidence
  provenance attestation or replay-proof trusted message. It is only a
  local lineage consistency fingerprint
- `FutureAuthorityPort`: a Python **type-only protocol** with an
  undefined response trust contract; there are **no** instantiated,
  selected or reachable providers
- `dispatch_unadmitted` and `accept_unadmitted_response`: both
  unconditionally raise `AuthorityConnectorNotAdmitted`, even if an
  injected object exposes the expected method or returns a
  plausible-looking approved/signed payload. The injected port is
  **never invoked**
- `CONTRACT_VERSION=ronas.authority.request.v1`,
  `CONNECTOR_STATE=NO_AUTHORITY_APPROVED` and an explicit list of
  unresolved external admission inputs. These are software vocabulary,
  **not** Business approval criteria/thresholds or policy decisions

This slice does not add a generic connector endpoint, a provider URL,
a bearer token, a transport adapter, a signed response parser,
a trust-on-first-use key or a fallback approval path.

## Transactional private request derivation

`SqliteSyntheticAuthorityEnquiryLedger.pending_connector_request_identities(
principal, domain)` is an internal-only method; **do not mount it as
an HTTP endpoint**. It first requires the exact, previously
Keycloak-verified domain operator Principal, verifies the version-pinned
local Business source files, then in one `BEGIN IMMEDIATE` transaction
re-verifies the source-handoff and enquiry append-only ledgers. Only
currently pending `CHECK_REFERENCE_REQUESTED` records yield request
identities. A later `TECHNICAL_RESPONSE_REF_RECORDED` removes that
channel's identity from the pending result; it still **does not**
authenticate the technical response or clear a blocker.

All identities are bound to the exact original source action/digest,
the enquiry action/digest and the pinned source revision. If event
lineage, file identity or the local hash chain is inconsistent, the
method fails closed. Concurrent local response writes are serialized;
this does not create a distributed transaction with an external
authority and does not authorize dispatch. The Python caller must
already be trusted to pass a verified Principal; constructing a
Principal manually is not an identity check.

## Opt-in, read-only administrative view

With the same explicitly injected LOCAL/TEST enquiry and handoff ledger
and signed Keycloak BrowserOIDC, the only new HTTP route is:

`GET /api/v1/admin/gate-evidence/{domain}/authority-connectors`

It returns **only** one status per existing requirement and technical
enquiry channel, always stating `NO_AUTHORITY_APPROVED`,
`dispatch_authorized=false`, `provider_response_trusted=false`,
`rights_verified=false`,
`reviewer_qualification_verified=false`, and
`business_gate_passed=false`. The public view does **not** expose
private source-action IDs, query reference IDs, event digests,
request fingerprints, actor digests, evidence bytes or provider
credentials. The full unresolved requirement list stays visible for
authorized domain operators as a diagnostic, not a request to
activate an integration. `governance` alone may inspect public
Business gate metadata but **not** this domain-technical route.

Missing/invalid identity returns 401, unknown or unassigned domain
404 and corrupted local history/source mismatch sanitized 503.
The default application does not mount the route. All mutation verbs
are unavailable. No source, person, right or reviewer is truly
verified, and there is no new UI environment.

## Required future human-approved admission contracts

Before even implementing a production provider adapter, separate
authorized Business/technical owners must explicitly specify, with
versioned evidence and appropriate review:

- the actual authorized organisation/source for each enquiry channel
  and permitted domain/purpose; current status **UNSELECTED**
- lawful consent, license/source rights, purpose limitation, permitted
  fields and retention/deletion responsibilities; **UNDEFINED**
- authenticated transport, issuer verification, signing/trust root,
  nonce or equivalent correlation, replay and expiry validation,
  revocation and incident behavior; **UNDEFINED**
- exact response schema/semantic meanings and signature verification;
  what constitutes a technical observation versus an authoritative
  determination; **UNDEFINED**
- reviewer credential/appointment and maker-checker validity,
  jurisdiction, independence and current authorisation; **UNDEFINED**
- permitted storage, private evidence scanner, encryption, audit
  anchoring, access controls and security/operational SLOs; **UNDECIDED**
- independent human Business evidence acceptance with explicit
  reference to the current, not historical, Gate state; **NOT GRANTED**

A future adapter must be evaluated against its *own approved contract*,
and even a verified external attestation must not promote a Business
Gate automatically. The locally versioned request fingerprint alone
does not constitute the future transport signature, request nonce,
provider identity or response-verification policy.

## Verification / governance

`backend/tests/test_gate_authority_connector_boundary.py` contains
**15 offline tests** for all 19 requirement slots across three domains,
fingerprint stability and action/digest binding, independent enquiry
channels, response transition, never-invoked injected mock port, forged
approval response denial, private/public separation, JWT and cookie
authorization, domain/Governance isolation, immutable GET-only API,
source drift and tampered ledger failure, opt-in/default-off and
concurrent response/pending-read behavior.

This feature is a **fail-closed connection boundary**, not an external
integration. Business Gate #2 Domestic, #3 Export, #4 Finance remain
OPEN. PR #1 and #9 stay Draft/Open/Unmerged; no Stage, QA Gate,
Release, Production or Merge is authorized.
