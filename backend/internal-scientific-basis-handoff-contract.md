# Ronas — in-house scientific provenance → internal AI proposal → assigned expert (LOCAL/TEST)

**Status:** DRAFT technical foundation in PR #9; **not** real scientific content, an approved Domestic D1 service, a source-licensing system, legal review, qualified agronomist certification, actual AI inference or Business Gate admission.

**Business source:** RON-DEC-014..021, RON-DEC-027/028/033; new [D1-SCI-01 internal source/rights/expert evidence candidate](../docs/business/79-internal-scientific-basis-provenance-and-expert-qualification.md) in Business PR #1, itself **unapproved**.

## Which independent questions must not be collapsed?

1. *Was a particular source/content/document version identified and recorded?* A version + SHA256-shaped digest is a structural fingerprint only. It **does not** independently prove the bytes were retrieved, signed or stored.
2. *Can Ronas lawfully use it for a household cultivation program?* Distinct rights evidence with verified, actual scope would be required. A synthetic rights-document identifier/digest or internal review note is **not** a licence.
3. *Is the material scientifically appropriate for this specific product/household?* Review by a genuinely qualified, authorized Ronas specialist with relevant scope and evidence, **independent of legal rights**, is still required.
4. *May the source be used in Training?* Separate evidence and rights are required, not derivable from program-use rights or a source being in the internal library.
5. *May the derived AI plan be followed?* Only separate human review and approval after genuine household consent/input adequacy, real model provenance and verified science; source existence is never plan approval.

## Versioned candidate shape — backend-only

`ronas_api/internal_scientific_basis_contract.py` contains immutable:
- `ScientificSourceCandidate`: exact DEMO ref/version, source content SHA256-shaped hash, independent **pointer** to a rights document/digest, independent **pointer** to a scientific-review request/material digest; purpose fixed to `DOMESTIC_CULTIVATION_PLAN`; status **fixed** `UNVERIFIED_SOURCE_CANDIDATE`.
- `ScientificBasisCandidate`: exact DEMO basis ID/version plus a nonempty tuple of uniquely identified sources; computes a **canonical SHA-256 manifest** over exact versions and all source, rights and review pointer data. Source ordering alone does not alter the digest.
- `inspect_scientific_basis_structure(basis, expected_manifest_digest, current_sources)`: compares the pinned proposal digest with the actual recomputed candidate fingerprint and checks every source against a **separate current source snapshot**. A source that disappears, changes version, content fingerprint, rights pointer/evidence or review pointer/evidence fails closed.

These fields are **not real source text**, rights/qualification evidence or legally reliable data. SHA syntax is not attestation. Even when the manifest is structurally current, outputs **always** indicate scientific/rights/qualification/Training approval false, no advice and no Business Gate pass.

## Integration with the existing authorized agronomy case reader

`SyntheticAgronomyWorkspace` can optionally receive (only in LOCAL/TEST) `scientific_basis_fixtures` and an independent `trusted_scientific_source_snapshot` callback. At construction, all selected proposal scientific-basis digests **must be present** and no duplicate or unbound basis can be accepted. On every exact-role+live-case-assigned specialist read, the *current* source snapshot is compared with the pinned manifest **inside the existing verified case/audit transaction**, along with the previously implemented versioned household input check. Failure or authority outage returns sanitized 503 and discloses **no stages**. Role/grant failure returns 404, and no source/rights/reviewer secret is included in GET payload. With no basis fixture, an explicit `SCIENTIFIC_SOURCE_UNVERIFIED` state is returned; existing read behavior continues and nothing is approved.

The specialist receives `scientific_basis_state=PROVENANCE_PINNED_UNVERIFIED` only when source manifest syntax and current revisions match; **not** `SCIENTIFICALLY_VALID`, `LICENSED`, `APPROVED` or an actionable plan.

**Negative test coverage:** arbitrary-purpose (Export/Training) contamination, forged review status or roles, invalid SHA/ref/version, duplicates, changed source bytes **fingerprint**, updated rights/review reference or digest, removed source, basis-version drift, independent callback unavailability, stale specialist handoff, no source/data leakage, and immutable/replay-safe existing audit.

## What is NOT yet implemented or decided

Real agricultural source files or authors; verifiable source licence/redistribution/Training rights; real professional qualification and signed review decision; scientific validation for a chosen crop/region/household; content-level conflict resolution; any numeric or plant-specific recommendation; model/dataset training; production source storage and retention/withdrawal; real household consent; operational approval APIs or case status transitions. The internal Ronas team can prepare all the knowledge/software deliverables, but verification of actual rights and scientific competence is a separate real obligation.

**Gates:** Domestic #2, Export #3, Finance #4 OPEN. Both PRs Draft/Open/Unmerged. No Ready for Review, Merge, Stage, QA, Release or Production.
