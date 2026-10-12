"""Reproducible, ephemeral LOCAL/TEST evidence handoff fingerprint.

This SHA-256 names only a synthetic structural reading; it is NOT signed,
persistent, scientifically verified or professionally assessed. The caller
must have separately verified the exact case and source authority.
"""
from __future__ import annotations

import hashlib
import json

from .expert_review_questions_sqlite import TRACKS
from .internal_cultivation_plan_contract import (
    InternalCultivationProposal, _digest,
)
from .scoped_drafts import _synthetic_ref

VERSION = "ronas.domestic.synthetic-independent-review-handoff.v0"
SOURCE_NONE = "NO_SEPARATE_SOURCE_CATALOGUE"
SOURCE_PINNED = "SOURCE_CANDIDATE_POINTERS_PINNED_UNVERIFIED"


def prepare_synthetic_review_handoff(
    *, case_ref: str, case_version: int,
    input_snapshot: tuple[int, str] | None,
    proposal: InternalCultivationProposal | None,
    source_state: str,
    question_rows: list[tuple],
    response_rows: list[tuple],
    sighting_rows: list[tuple],
) -> dict:
    """Fingerprint three independent synthetic evidence streams, no decisions.

    The rows are taken from the verified append-only SQLite ledger in one
    transaction. Read audit events are intentionally excluded from identity.
    """
    if (not _synthetic_ref(case_ref)
            or type(case_version) is not int or case_version < 1
            or source_state not in (SOURCE_NONE, SOURCE_PINNED)
            or type(question_rows) is not list
            or type(response_rows) is not list
            or type(sighting_rows) is not list):
        raise ValueError("invalid review handoff scope")
    if input_snapshot is not None and (
            type(input_snapshot) is not tuple
            or len(input_snapshot) != 2
            or type(input_snapshot[0]) is not int
            or input_snapshot[0] < 1 or not _digest(input_snapshot[1])):
        raise ValueError("invalid synthetic household input")
    if proposal is not None and (
            not isinstance(proposal, InternalCultivationProposal)
            or input_snapshot is None
            or proposal.household_case_ref != case_ref
            or proposal.household_case_version != case_version
            or proposal.household_input_revision != input_snapshot[0]
            or proposal.household_input_snapshot_digest != input_snapshot[1]):
        raise ValueError("untrusted proposal/current-input binding")
    if source_state == SOURCE_PINNED and proposal is None:
        raise ValueError("source pointer check cannot stand alone")

    by_track: dict[str, list[tuple]] = {track: [] for track in TRACKS}
    receipt_by_key: dict[tuple[str, int], tuple[str, int]] = {}
    ordered_questions = []
    last_q_sequence = 0
    for row in question_rows:
        if type(row) is not tuple or len(row) != 8:
            raise ValueError("malformed verified question row")
        track, rev, irev, ihash, shash, phash, receipt, seq = row
        if (track not in by_track or type(rev) is not int
                or rev != len(by_track[track]) + 1
                or type(irev) is not int or irev < 1
                or not all(_digest(x) for x in (ihash, shash, phash, receipt))
                or type(seq) is not int or seq <= last_q_sequence):
            raise ValueError("untrusted question ordering/receipt")
        last_q_sequence = seq
        key = (track, rev)
        receipt_by_key[key] = (receipt, seq)
        by_track[track].append(row)
        ordered_questions.append(row)

    def paired(rows: list[tuple], previous: dict | None) -> dict:
        linked = {}
        prev_sequence = 0
        for row in rows:
            if type(row) is not tuple or len(row) != 4:
                raise ValueError("malformed response/inspection row")
            track, rev, receipt, seq = row
            key = (track, rev)
            parent = (receipt_by_key.get(key) if previous is None
                      else previous.get(key))
            if (key[0] != TRACKS[0]
                    or parent is None
                    or not _digest(receipt)
                    or type(seq) is not int
                    or seq <= prev_sequence or seq <= parent[1]
                    or key in linked):
                raise ValueError("orphan/duplicated or unordered evidence receipt")
            linked[key] = (receipt, seq)
            prev_sequence = seq
        return linked

    responses = paired(response_rows, None)
    sightings = paired(sighting_rows, responses)

    tracks = []
    for track in TRACKS:
        hist = by_track[track]
        latest = hist[-1] if hist else None
        last_key = (track, latest[1]) if latest else None
        aligned = bool(
            latest is not None and input_snapshot is not None
            and proposal is not None and source_state == SOURCE_PINNED
            and latest[2] == input_snapshot[0]
            and latest[3] == input_snapshot[1]
            and latest[4] == proposal.scientific_basis_manifest_digest
            and latest[5] == proposal.proposal_content_digest
        )
        tracks.append({
            "track": track,
            "historical_question_count": len(hist),
            "historical_response_receipt_count": sum(
                (track, r[1]) in responses for r in hist
            ),
            "historical_sighting_receipt_count": sum(
                (track, r[1]) in sightings for r in hist
            ),
            "latest_question_revision": latest[1] if latest else None,
            "latest_question_fixture_binding_matches": aligned,
            "latest_owner_response_receipt_present": (
                last_key in responses if last_key else False
            ),
            "latest_specialist_receipt_sighting_present": (
                last_key in sightings if last_key else False
            ),
            "independent_specialist_review_recorded": False,
            "review_outcome": "NOT_REVIEWED",
        })

    # Version/purpose separated, exact identity is independent of read audits.
    canonical = {
        "contract_version": VERSION,
        "scope": ("LOCAL_TEST_SYNTHETIC_NOT_VERIFIED", "DOMESTIC",
                  case_ref, case_version),
        "input": input_snapshot,
        "source_pointer_state": source_state,
        "proposal": None if proposal is None else {
            "input_rev": proposal.household_input_revision,
            "input_hash": proposal.household_input_snapshot_digest,
            "science_manifest": proposal.scientific_basis_manifest_digest,
            "model_hash": proposal.internal_model_artifact_digest,
            "run_ref": proposal.internal_run_ref,
            "content_hash": proposal.proposal_content_digest,
            "origin": proposal.origin,
            "stages": [
                (s.ref, s.instructions_digest, s.observation_requirements_digest)
                for s in proposal.proposed_stages
            ],
        },
        "questions": ordered_questions,
        "responses": response_rows,
        "receipt_sightings": sighting_rows,
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode("ascii")
    fingerprint = hashlib.sha256(raw).hexdigest()
    return {
        "contract_version": VERSION,
        "engine": "DOMESTIC",
        "case_ref": case_ref,
        "case_version": case_version,
        "case_state": "DRAFT_ONLY",
        "snapshot_kind": "EPHEMERAL_SYNTHETIC_STRUCTURAL_CONTEXT",
        "context_fingerprint_sha256": fingerprint,
        "fingerprint_is_independent_attestation": False,
        "fingerprint_is_persisted_or_signed": False,
        "current_input_revision": (
            input_snapshot[0] if input_snapshot else None
        ),
        "source_candidate_pointer_state": source_state,
        "proposal_fixture_state": (
            "STRUCTURE_ONLY_UNREVIEWED" if proposal is not None
            else "NO_INTERNAL_PROPOSAL_FIXTURE"
        ),
        "tracks": tracks,
        "qualified_specialist_verified": False,
        "purpose_consent_verified": False,
        "scientific_suitability_verified": False,
        "service_use_rights_verified": False,
        "training_rights_verified": False,
        "model_execution_verified": False,
        "independent_decision_recorded": False,
        "plan_accepted": False,
        "new_advice_enabled": False,
        "real_data": False,
    }
