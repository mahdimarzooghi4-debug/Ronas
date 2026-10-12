# Ronas — Internal Cultivation Proposal Structural Envelope (Offline / LOCAL TEST)

**Status:** structural development contract only, NOT a real cultivation program,
not a production state machine, not an AI worker and not a human approval flow.
The business authority is RON-DEC-015..021 and the clarification
**RON-DEC-033 (Ronas-owned internal service creation)** recorded in [business
Draft PR #1](https://github.com/mahdimarzooghi4-debug/Ronas/pull/1).
The two PRs stay Draft/Open/Unmerged and all business gates stay OPEN.

## Value / who builds the service

Ronas **itself** develops and operates the scientific knowledge preparation,
household-specific plan-proposal capability, internal AI, expert review tools,
and plan-specific stage supervision. An external company or advisory service
is not a mandatory prerequisite to the **design** of this internal capability.
The agronomy expert can be a suitably qualified **Ronas team member**.
This does not override verifiable agronomic competence, real household consent,
scientific reference rights or legal authorizations. In particular, self-labeling
as `agronomy_expert` is not scientific qualification. An actual household
cultivation program is a different deliverable from its AI proposal.

## Actual approved future path (not activated here)

1. Household supplies cultivation inputs itself with informed consent, with
   a versioned and verified source context. Unknown or contradictory inputs
   cannot be guessed. AI **can suggest** gaps; household corrects; the expert
   explicitly validates sufficiency and science, otherwise plan acceptance halts.
2. Ronas-internal AI proposes a **household-specific** versioned cultivation
   program grounded in a reviewed/versioned scientific basis and an actual
   authorized model; the program's reporting stages derive from its content,
   **not** universal invented stage counts, dates or thresholds.
3. A qualified **internal Ronas specialist** independently reviews, revises or
   rejects the suggestion; ONLY explicit, audited and authorized acceptance
   makes a program effective. Neither a valid SHA-256 nor a review reference
   proves consent, input adequacy, qualified expert status or scientific quality.
4. Only stages of the accepted program may govern later supervision.
   A corrected household input invalidates the old program for **new advice**;
   old evidence remains intact; AI proposes a revised plan and independent
   expert reapproval. Historical observations may be mapped by AI but reuse
   needs the expert's explicit per-observation approval.
5. Product safety, inventory, publication, trade, prices and payment are
   independent and not automatically accepted by the cultivation program.

## Current code — structural verification only

`backend/ronas_api/internal_cultivation_plan_contract.py` contains frozen
`ProposedCultivationStage` and `InternalCultivationProposal` with exact
LOCAL/TEST synthetic references, case and input version, SHA-256-shaped input
snapshot, scientific-basis manifest, model artifact, proposal content and each
stage's instructions/observation-requirements digest, plus a synthetic
internal-run reference. The stage list must be nonempty and free of duplicate
stage refs; **no particular count, name, duration or agronomic instruction
is inferred**.

`inspect_proposal_structure(...)` compares expected DOMESTIC engine, case
identity/version, input revision and input digest supplied by a **separate
authoritative source**. The LOCAL/TEST `ProfileBackedProposalContextAuthority`
can now compose an explicit current case/source/model basis with the exact
profile ledger: it binds the current profile revision and canonical content
digest without returning profile values. Missing profiles, changed schema,
case-version mismatch or changed lineage fail closed; the runtime re-reads this
composite context around adapter execution, so a profile correction discards
an in-flight proposal. These internal ports are not mounted on HTTP and do not
make profile values available to the model adapter. Mismatches/stale inputs, external origin strings,
malformed hashes or unbound stages fail closed. This is a deterministic
LOCAL/TEST integrity-shape check: it does not fetch or cryptographically attest
scientific source rights, model weights, user consent, signing keys, or expert
identity; callers cannot self-assert those as facts.

Even a structurally matching proposal returns ONLY
`STRUCTURE_ONLY_UNREVIEWED` and `NOT_ACCEPTED`; scientific basis,
AI attestation, consent and specialist qualification/approval remain **false**;
stage activation, new cultivation advice, commercial actions and real-data
flags remain **false**. It exposes stage **references only**, not advice or
content. The `origin` marker is not a real internal AI execution attestation.
No HTTP endpoint, dataset, executable AI, professional review command, public
case mutation or business activation is created. The internal adapter and
profile-lineage ports are composable in LOCAL/TEST, while actual AI execution,
consent authority, evidence admission and expert decision adapters remain
separate integrations.

## Evidence required before moving beyond this offline boundary

- approved, versioned, rights-cleared real scientific source library;
- household-provided informed-consent input capture and amendments with
  clear fields, authorization and real lineage;
- internal licensed base-model checkpoint, training/evaluation datasets,
  real model-run evidence and independently checked output provenance;
- qualified Ronas internal expert registry with current authority,
  explicit plan-level review and recorded revisions;
- approved technical contract for reporting stages and recommendation
  suppression after input corrections, plus formal test and Gate approval.

**Tests:** `backend/tests/test_internal_cultivation_plan_contract.py`
covers structural success **without** acceptance, cross-engine isolation,
outside-model rejection, invalid and stale version/digests, duplicated
or malformed stages, expected case/engine binding, and no real advice
or approval. These are LOCAL/TEST tests, not real crop or AI validation.

**Gates:** Domestic #2, Export #3 and Finance #4 OPEN. RON-DEC-007 process
unchanged. No Ready for Review, merge, Stage, QA, deployment, sale or
Production permission.
