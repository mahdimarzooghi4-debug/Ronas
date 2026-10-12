"""Compare two case-local revisions of immutable synthetic evidence (LOCAL/TEST).

No prior AI proposal or source-catalogue snapshot is reconstructible from the
journal; only versioned input and question/owner-response/receipt events are.
No comparison here is approval, use-right, scientific or AI attestation.
"""
from __future__ import annotations

import hashlib
import json

from .expert_review_questions_sqlite import TRACKS
from .internal_cultivation_plan_contract import _digest
from .scoped_drafts import _synthetic_ref

VERSION = "ronas.domestic.synthetic-evidence-history-comparison.v0"
KINDS = ("HOUSEHOLD_INPUT_REVISION", "EXPERT_QUESTION",
         "OWNER_RESPONSE_RECEIPT", "EXPERT_RECEIPT_SIGHTING")


class EvidenceRevisionConflict(ValueError):
    """A requested case-local immutable evidence boundary does not exist."""


def verified_synthetic_evidence_events(
    *, input_rows: list[tuple], question_rows: list[tuple],
    response_rows: list[tuple], sighting_rows: list[tuple],
) -> list[tuple]:
    """Validate structurally linked rows from ONE previously verified ledger read.

    Returns sorted (global audit sequence, event kind, track, subject revision,
    canonical row excluding its audit sequence). Global sequence is internal
    only, never returned to a client.
    """
    if any(type(rows) is not list for rows in (
            input_rows, question_rows, response_rows, sighting_rows)):
        raise ValueError("malformed verified evidence collections")
    used_sequences = set()
    events = []

    def add(seq, kind, track, revision, canonical):
        if (type(seq) is not int or seq < 1 or seq in used_sequences):
            raise ValueError("invalid or duplicate evidence audit sequence")
        used_sequences.add(seq)
        events.append((seq, kind, track, revision, canonical))

    inputs = {}
    last_seq = 0
    for row in input_rows:
        if type(row) is not tuple or len(row) != 4:
            raise ValueError("malformed input revision")
        rev, manifest, receipt, seq = row
        if (type(rev) is not int or rev != len(inputs) + 1
                or not _digest(manifest) or not _digest(receipt)
                or type(seq) is not int or seq <= last_seq):
            raise ValueError("untrusted input revision continuity")
        inputs[rev] = (manifest, seq)
        add(seq, KINDS[0], None, rev, row[:-1])
        last_seq = seq

    questions = {}
    counts = {track: 0 for track in TRACKS}
    last_seq = 0
    for row in question_rows:
        if type(row) is not tuple or len(row) != 8:
            raise ValueError("malformed expert question")
        track, rev, input_rev, inp, science, proposal, receipt, seq = row
        source = inputs.get(input_rev) if type(input_rev) is int else None
        if (track not in counts or type(rev) is not int
                or rev != counts[track] + 1
                or source is None or inp != source[0]
                or not all(_digest(x) for x in (
                    inp, science, proposal, receipt))
                or type(seq) is not int or seq <= last_seq
                or source[1] >= seq):
            raise ValueError("untrusted question/input lineage")
        counts[track] = rev
        questions[(track, rev)] = seq
        add(seq, KINDS[1], track, rev, row[:-1])
        last_seq = seq

    responses = {}
    last_seq = 0
    for row in response_rows:
        if type(row) is not tuple or len(row) != 4:
            raise ValueError("malformed owner response")
        track, rev, receipt, seq = row
        parent = questions.get((track, rev)) if type(rev) is int else None
        if (track != TRACKS[0] or parent is None
                or not _digest(receipt)
                or type(seq) is not int or seq <= last_seq
                or seq <= parent or (track, rev) in responses):
            raise ValueError("untrusted owner response lineage")
        responses[(track, rev)] = seq
        add(seq, KINDS[2], track, rev, row[:-1])
        last_seq = seq

    sightings = set()
    last_seq = 0
    for row in sighting_rows:
        if type(row) is not tuple or len(row) != 4:
            raise ValueError("malformed specialist receipt sighting")
        track, rev, receipt, seq = row
        parent = responses.get((track, rev)) if type(rev) is int else None
        if (track != TRACKS[0] or parent is None
                or not _digest(receipt)
                or type(seq) is not int or seq <= last_seq
                or seq <= parent or (track, rev) in sightings):
            raise ValueError("untrusted receipt-sighting lineage")
        sightings.add((track, rev))
        add(seq, KINDS[3], track, rev, row[:-1])
        last_seq = seq
    events.sort(key=lambda e: e[0])
    return events


def _validate_case(case_ref: str, case_version: int, events: list[tuple]):
    if (not _synthetic_ref(case_ref)
            or type(case_version) is not int or case_version < 1
            or type(events) is not list):
        raise ValueError("invalid synthetic comparison scope")
    prev = 0
    for e in events:
        if (type(e) is not tuple or len(e) != 5
                or type(e[0]) is not int or e[0] <= prev
                or e[1] not in KINDS):
            raise ValueError("untrusted sorted event stream")
        prev = e[0]


def synthetic_evidence_timeline(
    *, case_ref: str, case_version: int, events: list[tuple],
) -> dict:
    _validate_case(case_ref, case_version, events)
    return {
        "contract_version": VERSION, "engine": "DOMESTIC",
        "case_ref": case_ref, "case_version": case_version,
        "case_state": "DRAFT_ONLY",
        "evidence_boundary_kind": "CASE_LOCAL_SYNTHETIC_MUTATION_ORDINAL",
        "latest_evidence_revision": len(events),
        "revisions": [{
            "evidence_revision": i,
            "event_kind": event[1],
            "track": event[2],
            "subject_revision": event[3],
            "independent_specialist_review_recorded": False,
        } for i, event in enumerate(events, start=1)],
        "global_audit_sequence_exposed": False,
        "historical_science_catalogue_reconstructible": False,
        "historical_ai_proposal_reconstructible": False,
        "real_data": False, "plan_accepted": False,
    }


def _snapshot(case_ref, case_version, events, boundary):
    selected = events[:boundary]
    latest_input = None
    latest_q = {t: None for t in TRACKS}
    counters = {t: {"questions": 0, "responses": 0, "sightings": 0}
                for t in TRACKS}
    for _, kind, track, _, fields in selected:
        if kind == KINDS[0]:
            latest_input = fields[0]
        elif kind == KINDS[1]:
            counters[track]["questions"] += 1
            latest_q[track] = fields
        elif kind == KINDS[2]:
            counters[track]["responses"] += 1
        else:
            counters[track]["sightings"] += 1

    canonical = {
        "contract_version": VERSION,
        "scope": ("LOCAL_TEST_IMMUTABLE_EVIDENCE", "DOMESTIC",
                  case_ref, case_version),
        "events": [(e[1], e[4]) for e in selected],
    }
    fingerprint = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")).hexdigest()

    return {
        "evidence_revision": boundary,
        "evidence_fingerprint_sha256": fingerprint,
        "latest_input_revision": latest_input,
        "tracks": [{
            "track": track, **counters[track],
            "latest_question_revision": (
                latest_q[track][1] if latest_q[track] else None
            ),
            "review_outcome": "NOT_REVIEWED",
        } for track in TRACKS],
    }, latest_q


def compare_synthetic_evidence_revisions(
    *, case_ref: str, case_version: int, events: list[tuple],
    from_revision: int, to_revision: int,
) -> dict:
    _validate_case(case_ref, case_version, events)
    if (type(from_revision) is not int or type(to_revision) is not int
            or not 1 <= from_revision < to_revision <= len(events)):
        raise EvidenceRevisionConflict("unknown/invalid case-local evidence boundary")
    before, before_last_q = _snapshot(case_ref, case_version, events, from_revision)
    after, after_last_q = _snapshot(case_ref, case_version, events, to_revision)
    if before["evidence_fingerprint_sha256"] == after["evidence_fingerprint_sha256"]:
        raise ValueError("distinct verified evidence revisions share a fingerprint")
    changes = []
    for track, old, new in zip(TRACKS, before["tracks"], after["tracks"]):
        old_q, new_q = before_last_q[track], after_last_q[track]
        changes.append({
            "track": track,
            "added_question_count": new["questions"] - old["questions"],
            "added_owner_response_count": new["responses"] - old["responses"],
            "added_receipt_sighting_count": new["sightings"] - old["sightings"],
            "latest_question_revision_changed": (
                old["latest_question_revision"] != new["latest_question_revision"]
            ),
            "latest_question_pinned_science_manifest_changed": (
                (old_q[4] if old_q else None) !=
                (new_q[4] if new_q else None)
            ),
            "latest_question_pinned_proposal_digest_changed": (
                (old_q[5] if old_q else None) !=
                (new_q[5] if new_q else None)
            ),
            "review_outcome": "NOT_REVIEWED",
            "eligible_for_operational_reuse": False,
        })
    return {
        "contract_version": VERSION, "engine": "DOMESTIC",
        "case_ref": case_ref, "case_version": case_version,
        "case_state": "DRAFT_ONLY",
        "comparison_scope": "VERIFIED_HISTORICAL_SYNTHETIC_LEDGER_ONLY",
        "from": before, "to": after,
        "input_revision_changed": (
            before["latest_input_revision"] != after["latest_input_revision"]
        ),
        "track_deltas": changes,
        "historical_science_catalogue_reconstructible": False,
        "historical_ai_proposal_reconstructible": False,
        "fingerprint_is_signature_or_approval": False,
        "qualified_specialist_verified": False,
        "consent_verified": False,
        "scientific_validity_verified": False,
        "source_rights_verified": False,
        "independent_decision_recorded": False,
        "plan_accepted": False, "new_advice_enabled": False,
        "real_data": False,
    }
