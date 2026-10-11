"""Synthetic, explicitly assigned agronomy case preview for the shared user UI.

There is no certified agronomist registry, real consent, cultivation inputs,
expert decision or authorized cultivation plan. This adapter is LOCAL/TEST
only, and must be mounted only with the *identical* Keycloak-scoped review
ledger. Signed agronomy_expert role alone cannot select a household case.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .auth import Principal
from .grant_ledger_sqlite import LedgerIntegrityError
from .household_input_ledger_sqlite import SqliteSyntheticHouseholdInputLedger
from .domestic_preparation_preview import domestic_preparation_preview
from .internal_cultivation_plan_contract import (
    InternalCultivationProposal, _digest, inspect_proposal_structure,
)
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger, STATES
from .internal_expert_review_preparation import project_expert_review_preparation
from .expert_review_questions_sqlite import (
    SqliteSyntheticExpertQuestionLedger, ReviewQuestionConflict, TRACKS,
)
from .scoped_drafts import _synthetic_ref, _synthetic_subject
from .internal_scientific_basis_contract import (
    ScientificBasisCandidate, ScientificSourceCandidate,
    inspect_scientific_basis_structure,
)


@dataclass(frozen=True, slots=True)
class SyntheticAgronomyAssignment:
    ref: str
    subject: str
    case_version: int

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.ref)
                or not _synthetic_subject(self.subject)
                or type(self.case_version) is not int or self.case_version < 1):
            raise ValueError("invalid explicit synthetic expert assignment")


class SyntheticAgronomyWorkspace:
    """Separate role+case authorization, without reusing domestic_ops grants."""

    def __init__(
        self, ledger: SqliteSyntheticHumanReviewLedger,
        assignments: Iterable[SyntheticAgronomyAssignment], *,
        trusted_assignment_active: Callable[[str, str, int], bool],
        proposal_fixtures: Iterable[InternalCultivationProposal] = (),
        trusted_input_snapshot: Callable[[str, int], tuple[int, str] | None] | None = None,
        scientific_basis_fixtures: Iterable[ScientificBasisCandidate] = (),
        trusted_scientific_source_snapshot: Callable[
            [], tuple[ScientificSourceCandidate, ...]
        ] | None = None,
    ) -> None:
        if (not isinstance(ledger, SqliteSyntheticHumanReviewLedger)
                or not callable(trusted_assignment_active)):
            raise ValueError("explicit ledger and live assignment authority required")
        bound: dict[tuple[str, str], SyntheticAgronomyAssignment] = {}
        for assignment in assignments:
            if not isinstance(assignment, SyntheticAgronomyAssignment):
                raise ValueError("unexpected agronomy assignment type")
            record = ledger._catalogue.get(("DOMESTIC", assignment.ref))
            if record is None or record.version != assignment.case_version:
                raise ValueError("assignment must pin an exact DOMESTIC case/version")
            key = assignment.subject, assignment.ref
            if key in bound:
                raise ValueError("duplicate agronomy case assignment")
            bound[key] = assignment
        # Optional LOCAL/TEST fixtures never attest real model execution.
        # Input binding must be checked against a separate source.
        catalog: dict[str, InternalCultivationProposal] = {}
        for fixture in proposal_fixtures:
            if not isinstance(fixture, InternalCultivationProposal):
                raise ValueError("untrusted synthetic AI proposal fixture")
            record = ledger._catalogue.get(("DOMESTIC", fixture.household_case_ref))
            if (record is None
                    or fixture.household_case_version != record.version
                    or fixture.household_case_ref in catalog):
                raise ValueError("proposal fixture case/version not pinned")
            catalog[fixture.household_case_ref] = fixture
        if (isinstance(ledger, SqliteSyntheticHouseholdInputLedger)
                and trusted_input_snapshot is not None):
            # The persisted household owner journal is the sole authority.
            # An injected callback must never override a newer correction
            # to revive a stale AI proposal.
            raise ValueError("conflicting household input authorities")
        if (catalog and not (callable(trusted_input_snapshot)
                             or isinstance(ledger, SqliteSyntheticHouseholdInputLedger))
                or trusted_input_snapshot is not None
                   and not callable(trusted_input_snapshot)):
            raise ValueError("independent input snapshot authority required")
        # A pinned, *unverified* scientific provenance catalogue is entirely
        # optional and must have a separately read current-source authority.
        # Structural provenance never authorizes a source or plan.
        bases: dict[str, ScientificBasisCandidate] = {}
        for basis in scientific_basis_fixtures:
            if not isinstance(basis, ScientificBasisCandidate):
                raise ValueError("untrusted scientific basis fixture")
            digest = basis.manifest_digest
            if digest in bases:
                raise ValueError("duplicate scientific basis")
            bases[digest] = basis
        if ((bases and not callable(trusted_scientific_source_snapshot))
                or trusted_scientific_source_snapshot is not None
                   and not callable(trusted_scientific_source_snapshot)):
            raise ValueError("current scientific source authority required")
        if bases and not catalog:
            raise ValueError("scientific basis without proposal")
        if bases and any(
            item.scientific_basis_manifest_digest not in bases
            for item in catalog.values()
        ):
            raise ValueError("unbound scientific basis digest")
        self._scientific_basis_fixtures = bases
        self._trusted_scientific_sources = trusted_scientific_source_snapshot
        self._proposal_fixtures = catalog
        self._trusted_input_snapshot = trusted_input_snapshot
        self.ledger = ledger
        self._assignments = bound
        self._live_authority = trusted_assignment_active

    @staticmethod
    def _actor(principal: Principal) -> str | None:
        if (not isinstance(principal, Principal)
                or not _synthetic_subject(principal.subject)
                or "agronomy_expert" not in principal.roles):
            return None
        return principal.subject

    def _allowed(self, subject: str, ref: str, version: int) -> bool:
        assignment = self._assignments.get((subject, ref))
        if assignment is None or assignment.case_version != version:
            return False
        try:
            # This is NOT a real professional-qualification authority. It is
            # only current, explicit LOCAL/TEST case access permission.
            return self._live_authority(subject, ref, version) is True
        except Exception as exc:
            raise LedgerIntegrityError("agronomy assignment authority unavailable") from exc

    def _preview(self, db, ref: str) -> dict:
        record = self.ledger._catalogue[("DOMESTIC", ref)]
        versions = tuple(row[0] for row in db.execute(
            "SELECT version FROM case_history "
            "WHERE engine='DOMESTIC' AND ref=? ORDER BY version", (ref,),
        ))
        if (versions != self.ledger._histories[("DOMESTIC", ref)]
                or not versions or versions[-1] != record.version):
            raise LedgerIntegrityError("agronomy case history mismatch")
        steps = self.ledger._steps(db, "DOMESTIC", ref)
        preparation = domestic_preparation_preview(
            case_version=record.version,
            review_revision=len(steps),
            technical_review_state=STATES[len(steps)],
            valid_review_states=STATES,
            observed_review_steps=tuple(
                item.stage for item in steps
            ),
        )
        return {
            "ref": ref,
            "engine": "DOMESTIC",
            "case_version": record.version,
            "known_versions": list(versions),
            "case_status": "DRAFT_ONLY",
            "source": "SYNTHETIC_ONLY",
            "review_revision": len(steps),
            "technical_review_state": STATES[len(steps)],
            "technical_review_steps": [
                {"revision": item.revision, "stage": item.stage}
                for item in steps
            ],
            "cultivation_preparation": preparation,
            "cultivation_inputs": preparation["cultivation_inputs"],
            "plan_state": preparation["plan_state"],
            "agronomist_qualification_verified": preparation[
                "agronomist_qualification_verified"
            ],
            "purpose_consent_verified": preparation["purpose_consent_verified"],
            "scientific_review_approved": preparation["scientific_review_approved"],
            "plan_accepted": preparation["plan_accepted"],
            "real_data": preparation["real_data"],
            "business_actions_enabled": preparation["business_actions_enabled"],
        }

    def read_assigned_case(self, ref: str, principal: Principal) -> dict | None:
        if not _synthetic_ref(ref):
            return None
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            record = self.ledger._catalogue.get(("DOMESTIC", ref))
            subject = self._actor(principal)
            if record is None or subject is None:
                return None
            allowed = self._allowed(subject, ref, record.version)
            result = self._preview(db, ref) if allowed else None
            self.ledger._append(
                db, kind="READ_ALLOWED" if allowed else "READ_DENIED",
                engine="DOMESTIC", ref=ref, actor=subject,
                mode="AGRONOMY_ASSIGNED_CASE",
            )
            return result

    def list_assigned_cases(
        self, principal: Principal, *, after_ref: str | None = None,
        limit: int = 20, technical_state: str = "ALL",
    ) -> dict:
        if (type(limit) is not int or not 1 <= limit <= 50
                or after_ref is not None and not _synthetic_ref(after_ref)
                or technical_state not in ("ALL", *STATES)):
            raise ValueError("invalid synthetic agronomy list request")
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            subject = self._actor(principal)
            refs = []
            if subject is not None:
                for actor, ref in sorted(self._assignments):
                    if actor != subject or after_ref is not None and ref <= after_ref:
                        continue
                    record = self.ledger._catalogue.get(("DOMESTIC", ref))
                    if (record is None
                            or not self._allowed(subject, ref, record.version)):
                        continue
                    # Filter only AFTER exact role, live assignment and
                    # immutable case history verification. No hidden-case
                    # counts, inferred science or unauthorized cursor leaks.
                    data = self._preview(db, ref)
                    if (technical_state == "ALL"
                            or data["technical_review_state"] == technical_state):
                        refs.append((ref, data))
            selected = refs[:limit]
            items = []
            for ref, data in selected:
                items.append({
                    "ref": ref, "engine": "DOMESTIC",
                    "case_version": data["case_version"],
                    "case_status": "DRAFT_ONLY",
                    "technical_review_state": data["technical_review_state"],
                    "plan_state": "NOT_AUTHORED",
                    "agronomist_qualification_verified": False,
                    "plan_accepted": False,
                })
                self.ledger._append(
                    db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                    actor=subject, mode="AGRONOMY_ASSIGNED_WORKLIST",
                )
            return {
                "engine": "DOMESTIC",
                "items": items,
                "next_cursor": selected[-1][0] if len(refs) > limit else None,
            }

    def read_assigned_proposal_structure(
        self, ref: str, principal: Principal,
    ) -> dict | None:
        """Audited, assigned specialist-only, read-only synthetic AI handoff.

        A technical review response is never cultivation-plan approval.
        """
        if not _synthetic_ref(ref):
            return None
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            record = self.ledger._catalogue.get(("DOMESTIC", ref))
            subject = self._actor(principal)
            if record is None or subject is None:
                return None
            allowed = self._allowed(subject, ref, record.version)
            result = None
            if allowed:
                case = self._preview(db, ref)
                proposal = self._proposal_fixtures.get(ref)
                if proposal is None:
                    result = {
                        "contract_version": "ronas.domestic.internal-proposal-handoff.v0",
                        "engine": "DOMESTIC", "case_ref": ref,
                        "case_version": record.version,
                        "proposal_status": "NO_INTERNAL_PROPOSAL_FIXTURE",
                        "input_state": case["cultivation_preparation"]["input_state"],
                        "cultivation_inputs": case["cultivation_inputs"],
                        "technical_review_state": case["technical_review_state"],
                        "plan_state": "NOT_AUTHORED",
                        "expert_qualification_verified": False,
                        "scientific_review_approved": False,
                        "plan_accepted": False,
                        "advice_enabled": False, "real_data": False,
                    }
                else:
                    authority = self._trusted_input_snapshot
                    try:
                        if isinstance(self.ledger, SqliteSyntheticHouseholdInputLedger):
                            # Current persisted owner revision always wins.
                            # No callback can override the revised snapshot;
                            # reuse the verified transaction (no DB deadlock).
                            snapshot = self.ledger._input_snapshot_from_verified_transaction(
                                db, ref, record.version,
                            )
                        elif authority is not None:
                            snapshot = authority(ref, record.version)
                        else:
                            raise LedgerIntegrityError("input authority not configured")
                    except Exception as exc:
                        raise LedgerIntegrityError(
                            "synthetic input snapshot source unavailable"
                        ) from exc
                    if (not isinstance(snapshot, tuple)
                            or len(snapshot) != 2
                            or type(snapshot[0]) is not int
                            or snapshot[0] < 1
                            or not _digest(snapshot[1])):
                        raise LedgerIntegrityError(
                            "missing/invalid independent synthetic input snapshot"
                        )
                    try:
                        traced = inspect_proposal_structure(
                            proposal, expected_case_engine="DOMESTIC",
                            expected_case_ref=ref,
                            expected_case_version=record.version,
                            expected_input_revision=snapshot[0],
                            expected_input_snapshot_digest=snapshot[1],
                        )
                    except ValueError as exc:
                        raise LedgerIntegrityError(
                            "stale/mismatched synthetic proposal lineage"
                        ) from exc
                    provenance_state = "SCIENTIFIC_SOURCE_UNVERIFIED"
                    if self._scientific_basis_fixtures:
                        basis = self._scientific_basis_fixtures.get(
                            proposal.scientific_basis_manifest_digest,
                        )
                        try:
                            latest = self._trusted_scientific_sources()
                            science_trace = inspect_scientific_basis_structure(
                                basis,
                                expected_manifest_digest=(
                                    proposal.scientific_basis_manifest_digest
                                ),
                                current_sources=latest,
                            )
                        except Exception as exc:
                            raise LedgerIntegrityError(
                                "stale/unavailable internal scientific source lineage"
                            ) from exc
                        provenance_state = science_trace["basis_state"]
                    # Client receives no digests, source content/rights
                    # references, model ref or scientific approval.
                    result = {
                        "contract_version": "ronas.domestic.internal-proposal-handoff.v0",
                        "engine": "DOMESTIC", "case_ref": ref,
                        "case_version": record.version,
                        "proposal_status": traced["proposal_status"],
                        "scientific_basis_state": provenance_state,
                        "proposed_stage_refs": traced["proposed_stage_refs"],
                        "input_revision": snapshot[0],
                        "input_state": case["cultivation_preparation"]["input_state"],
                        "technical_review_state": case["technical_review_state"],
                        "plan_state": "NOT_AUTHORED",
                        "expert_qualification_verified": False,
                        "scientific_review_approved": False,
                        "plan_accepted": False,
                        "advice_enabled": False, "real_data": False,
                    }
                self.ledger._append(
                    db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                    actor=subject, mode="AGRONOMY_INTERNAL_PROPOSAL_HANDOFF",
                )
            else:
                self.ledger._append(
                    db, kind="READ_DENIED", engine="DOMESTIC", ref=ref,
                    actor=subject, mode="AGRONOMY_INTERNAL_PROPOSAL_HANDOFF",
                )
            return result

    def read_assigned_expert_review_preparation(
        self, ref: str, principal: Principal,
    ) -> dict | None:
        """One role-and-live-assignment-verified, audited dossier read.

        Reuses the exact same checked case/input/science proposal snapshot;
        no second read can mix revisions, no unaudited review privileges
        or write/approve command are created.
        """
        snapshot = self.read_assigned_proposal_structure(ref, principal)
        if snapshot is None:
            return None
        try:
            return project_expert_review_preparation(snapshot)
        except (ValueError, KeyError, TypeError) as exc:
            raise LedgerIntegrityError(
                "untrusted synthetic expert review preparation source"
            ) from exc

    def record_assigned_synthetic_review_question(
        self, ref: str, principal: Principal, *, action_id: str,
        track: str, expected_case_version: int, expected_input_revision: int,
        expected_question_revision: int, reason_ref: str, evidence_ref: str,
    ) -> dict | None:
        """Record a missing-evidence QUESTION, never a review finding.

        Caller supplies a signature-verified principal; on every request we
        recheck live assignment, owner input and any independently pinned
        science source. The same SQLite transaction writes the question
        and the existing append-only audit chain, without stale TOCTOU.
        """
        if not isinstance(self.ledger, SqliteSyntheticExpertQuestionLedger):
            raise ValueError("synthetic question journal not installed")
        if not _synthetic_ref(ref):
            return None
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            record = self.ledger._catalogue.get(("DOMESTIC", ref))
            actor = self._actor(principal)
            if record is None or actor is None:
                return None
            if not self._allowed(actor, ref, record.version):
                return None
            if (type(expected_case_version) is not int
                    or expected_case_version != record.version):
                raise ReviewQuestionConflict("case version changed")
            if track not in TRACKS:
                raise ValueError("unrecognized expert question track")
            proposal = self._proposal_fixtures.get(ref)
            if proposal is None:
                # No fake model proposal or technical-response event can be
                # substituted for a reviewable snapshot.
                raise ReviewQuestionConflict("no pinned synthetic proposal")
            snapshot = self.ledger._input_snapshot_from_verified_transaction(
                db, ref, record.version,
            )
            if (snapshot is None or type(expected_input_revision) is not int
                    or snapshot[0] != expected_input_revision):
                raise ReviewQuestionConflict("current household input differs")
            try:
                inspect_proposal_structure(
                    proposal, expected_case_engine="DOMESTIC",
                    expected_case_ref=ref, expected_case_version=record.version,
                    expected_input_revision=snapshot[0],
                    expected_input_snapshot_digest=snapshot[1],
                )
            except ValueError as exc:
                raise ReviewQuestionConflict(
                    "stale synthetic model proposal input"
                ) from exc
            if self._scientific_basis_fixtures:
                basis = self._scientific_basis_fixtures.get(
                    proposal.scientific_basis_manifest_digest
                )
                try:
                    latest = self._trusted_scientific_sources()
                    inspect_scientific_basis_structure(
                        basis,
                        expected_manifest_digest=proposal.scientific_basis_manifest_digest,
                        current_sources=latest,
                    )
                except Exception as exc:
                    raise ReviewQuestionConflict(
                        "stale/unavailable scientific reference"
                    ) from exc
            return self.ledger._append_verified_question(
                db, ref=ref, case_version=record.version, actor=actor,
                track=track, action_id=action_id,
                expected_revision=expected_question_revision,
                input_revision=snapshot[0], input_digest=snapshot[1],
                science_digest=proposal.scientific_basis_manifest_digest,
                proposal_digest=proposal.proposal_content_digest,
                reason_ref=reason_ref, evidence_ref=evidence_ref,
            )

    def inspect_assigned_synthetic_response_receipt(
        self, ref: str, principal: Principal, *, action_id: str,
        expected_case_version: int, expected_input_revision: int,
        expected_question_revision: int,
    ) -> dict | None:
        """Presence-only inspection, NOT judging reply, input or plan.

        Bind to exactly current owner input, question, structural model and
        current scientific source snapshot within the SAME audited transaction.
        """
        if not isinstance(self.ledger, SqliteSyntheticExpertQuestionLedger):
            raise ValueError("synthetic response receipt ledger not mounted")
        if not _synthetic_ref(ref):
            return None
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            record = self.ledger._catalogue.get(("DOMESTIC", ref))
            actor = self._actor(principal)
            if record is None or actor is None:
                return None
            if not self._allowed(actor, ref, record.version):
                return None
            if (type(expected_case_version) is not int
                    or expected_case_version != record.version):
                raise ReviewQuestionConflict("case version changed")
            proposal = self._proposal_fixtures.get(ref)
            if proposal is None:
                raise ReviewQuestionConflict("no current synthetic proposal")
            snapshot = self.ledger._input_snapshot_from_verified_transaction(
                db, ref, record.version,
            )
            if (snapshot is None or type(expected_input_revision) is not int
                    or snapshot[0] != expected_input_revision):
                raise ReviewQuestionConflict("household input changed")
            try:
                inspect_proposal_structure(
                    proposal, expected_case_engine="DOMESTIC",
                    expected_case_ref=ref,
                    expected_case_version=record.version,
                    expected_input_revision=snapshot[0],
                    expected_input_snapshot_digest=snapshot[1],
                )
            except ValueError as exc:
                raise ReviewQuestionConflict("stale synthetic proposal") from exc
            if self._scientific_basis_fixtures:
                basis = self._scientific_basis_fixtures.get(
                    proposal.scientific_basis_manifest_digest,
                )
                try:
                    inspect_scientific_basis_structure(
                        basis,
                        expected_manifest_digest=(
                            proposal.scientific_basis_manifest_digest
                        ),
                        current_sources=self._trusted_scientific_sources(),
                    )
                except Exception as exc:
                    raise ReviewQuestionConflict(
                        "stale/unavailable scientific lineage"
                    ) from exc
            return self.ledger._append_verified_response_receipt_inspection(
                db, ref=ref, case_version=record.version, actor=actor,
                action_id=action_id,
                question_revision=expected_question_revision,
                input_revision=snapshot[0], input_digest=snapshot[1],
                science_digest=proposal.scientific_basis_manifest_digest,
                proposal_digest=proposal.proposal_content_digest,
            )

    def read_assigned_synthetic_review_questions(
        self, ref: str, principal: Principal,
    ) -> dict | None:
        """Read historical questions independently of current plan validity.

        A changed input/source must not delete original evidence. No
        historical question becomes a current expert approval or action.
        """
        if not isinstance(self.ledger, SqliteSyntheticExpertQuestionLedger):
            raise ValueError("synthetic question journal not installed")
        if not _synthetic_ref(ref):
            return None
        with self.ledger._transaction() as db:
            self.ledger._verify(db)
            record = self.ledger._catalogue.get(("DOMESTIC", ref))
            actor = self._actor(principal)
            if record is None or actor is None:
                return None
            if not self._allowed(actor, ref, record.version):
                return None
            rows = self.ledger._history(db, ref)
            # Only a receipt-present marker crosses into the expert view;
            # the owner's synthetic response/evidence refs remain private.
            answered = set(db.execute(
                "SELECT track,question_revision FROM household_question_response "
                "WHERE ref=?", (ref,),
            ))
            inspected = set(db.execute(
                "SELECT track,question_revision "
                "FROM expert_response_receipt_inspection WHERE ref=?",
                (ref,),
            ))
            self.ledger._append(
                db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                actor=actor, mode="AGRONOMY_SYNTHETIC_QUESTION_HISTORY",
            )
            return {
                "contract_version":
                    "ronas.domestic.synthetic-expert-question-history.v0",
                "engine": "DOMESTIC", "case_ref": ref,
                "case_version": record.version,
                "questions": [
                    {"track": track, "question_revision": rev,
                     "bound_input_revision": bound_input_revision,
                     "draft_reason_ref": reason, "draft_evidence_ref": evidence,
                     "record_state": "HISTORICAL_QUESTION_ONLY_NOT_REVIEWED",
                     "synthetic_household_response_received": (
                         track, rev
                     ) in answered,
                     "response_is_expert_approval": False,
                     "synthetic_receipt_inspected_not_reviewed": (
                         track, rev
                     ) in inspected,
                     "inspection_is_expert_decision": False}
                    for track, rev, bound_input_revision, reason, evidence in rows
                ],
                "qualification_verified": False,
                "questions_are_review_decisions": False,
                "plan_accepted": False, "new_advice_enabled": False,
                "real_data": False,
            }
