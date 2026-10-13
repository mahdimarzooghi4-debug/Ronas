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
