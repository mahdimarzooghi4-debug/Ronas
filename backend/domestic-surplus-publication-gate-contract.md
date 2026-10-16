# Domestic surplus publication authorization core (LOCAL/TEST)

This version-bound gate encodes the approved separation between a non-public
surplus draft, producer publication approval, and an independent quality/safety
verification. It performs no automatic public publication and defines no
product, quantity, unit, price, or quality criteria schema.

The read endpoint is mounted only when a trusted owner-scoped authority resolver
is explicitly supplied. Both attestations must bind to the exact current offer
revision and payload digest. The producer must match the offer owner; the
quality/safety attestor must be independently identified and its authority
verified by the resolver. A changed offer version invalidates both attestations.

Seller eligibility, active household permission, and the Domestic marketplace
gate are separate default-closed inputs. Missing or false inputs keep the offer
in NON_PUBLIC_DRAFT. PUBLICATION_AUTHORIZED only means these technical checks
passed for the snapshot; this module does not publish, expose a buyer listing,
establish food-safety criteria, create a sale, or move money. Domestic Issue #2
remains open.

Validation covers version and digest drift, missing/rejected attestations,
wrong producer, same-actor quality verification, independent default-closed
admission gates, owner scoping, authority failures, and a projection that never
exposes private evidence or claims publication.


When the private surplus draft ledger is composed into readiness, the evaluated
candidate is the owner's exact latest persisted revision and payload digest. The
resolver must independently return the same version and current attestations; older
approvals produce version/staleness blockers. A draft whose schema digest is no
longer active receives OFFER_SCHEMA_CHANGED and cannot pass the technical gate.
No field values are returned by the readiness projection.

Readiness also requires the persisted offer to be bound to the current household
input revision. An unbound offer, a changed household input, or an unavailable
input-lineage reader adds a dedicated blocker. The input revision is read again
after resolving external authorities so a concurrent correction cannot leave an
older household context appearing eligible.
