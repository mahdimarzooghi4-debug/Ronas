"""Independent, append-only technical authority *enquiry* ledger (LOCAL/TEST).

Records requests and DEMO response **references** against an immutable
evidence-handoff reference. It does not call an external provider, qualify
a reviewer, verify any right, assess response text, or approve a Business gate.
All direct callers must already have a verified Keycloak Principal.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable
import sqlite3

from .auth import Principal
from .business_gate_evidence import BUSINESS_SOURCE_SHA, verify_pinned_business_sources
from .gate_evidence_handoff_sqlite import (
    GENESIS, HandoffConflict, HandoffIntegrityError, HandoffNotAuthorized,
    SqliteSyntheticGateEvidenceHandoff, _ref, canonical, digest,
)

CHECKS = ("ORIGIN", "SOURCE_RIGHTS", "REVIEWER_QUALIFICATION")
REQUESTED = "CHECK_REFERENCE_REQUESTED"
RESPONDED = "TECHNICAL_RESPONSE_REF_RECORDED"


@dataclass(frozen=True, slots=True)
class AuthorityEnquiryEvent:
    sequence: int
    action_id: str
    domain: str
    evidence_id: str
    check_kind: str
    stage: str
    revision: int
    actor_digest: str
    source_action_id: str
    source_event_digest: str
    request_ref: str
    response_ref: str | None
    previous_digest: str
    event_digest: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_digest"}


class SqliteSyntheticAuthorityEnquiryLedger:
    """Same LOCAL SQLite transaction as the already-verified handoff ledger."""

    def __init__(
        self, handoff: SqliteSyntheticGateEvidenceHandoff, *,
        trusted_response_authorizer: Callable[[str, str, str, str], bool],
    ):
        if not isinstance(handoff, SqliteSyntheticGateEvidenceHandoff):
            raise ValueError("explicit handoff ledger required")
        if not callable(trusted_response_authorizer):
            raise ValueError("explicit independent response authorizer required")
        self.handoff = handoff
        self._response_authorizer = trusted_response_authorizer
        verify_pinned_business_sources()
        with handoff._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS authority_enquiry_event (
                    sequence INTEGER PRIMARY KEY,
                    action_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    previous_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS authority_enquiry_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS authority_enquiry_no_update
                BEFORE UPDATE ON authority_enquiry_event
                BEGIN SELECT RAISE(ABORT, 'append-only enquiry'); END;
                CREATE TRIGGER IF NOT EXISTS authority_enquiry_no_delete
                BEFORE DELETE ON authority_enquiry_event
                BEGIN SELECT RAISE(ABORT, 'append-only enquiry'); END;
            """)
        with handoff._transaction() as db:
            row = db.execute(
                "SELECT value FROM authority_enquiry_meta WHERE key='source_sha'"
            ).fetchone()
            if row is None:
                if db.execute("SELECT count(*) FROM authority_enquiry_meta").fetchone()[0]:
                    raise HandoffIntegrityError("incomplete enquiry metadata")
                db.execute(
                    "INSERT INTO authority_enquiry_meta VALUES ('source_sha', ?)",
                    (BUSINESS_SOURCE_SHA,),
                )
                db.execute(
                    "INSERT INTO authority_enquiry_meta VALUES ('head', ?)",
                    (GENESIS,),
                )
            self._verify(db)

    def _verify(self, db: sqlite3.Connection) -> tuple[list, list[AuthorityEnquiryEvent]]:
        handoffs = self.handoff._verify(db)
        origin = {
            (e.domain, e.evidence_id): e for e in handoffs
            if e.stage == "REFERENCE_RECORDED"
        }
        meta = dict(db.execute("SELECT key, value FROM authority_enquiry_meta"))
        if (set(meta) != {"source_sha", "head"}
                or meta["source_sha"] != BUSINESS_SOURCE_SHA):
            raise HandoffIntegrityError("invalid enquiry source identity")
        prev = GENESIS
        last: dict[tuple[str, str, str], AuthorityEnquiryEvent] = {}
        actions: set[str] = set()
        events: list[AuthorityEnquiryEvent] = []
        for seq, action, payload, stamp, previous in db.execute(
            "SELECT sequence, action_id, payload, digest, previous_digest "
            "FROM authority_enquiry_event ORDER BY sequence"
        ):
            try:
                data = __import__("json").loads(payload)
                event = AuthorityEnquiryEvent(**data, event_digest=stamp)
            except (TypeError, ValueError, KeyError) as exc:
                raise HandoffIntegrityError("invalid enquiry event") from exc
            key = (event.domain, event.evidence_id, event.check_kind)
            former = last.get(key)
            source = origin.get(key[:2])
            if (
                type(seq) is not int or seq != len(events) + 1
                or type(event.sequence) is not int or event.sequence != seq
                or event.action_id != action or not _ref(action) or action in actions
                or previous != prev or event.previous_digest != prev
                or source is None or event.check_kind not in CHECKS
                or event.source_action_id != source.action_id
                or event.source_event_digest != source.event_digest
                or not _ref(event.request_ref)
                or not isinstance(event.actor_digest, str)
                or len(event.actor_digest) != 64
                or any(x not in "0123456789abcdef" for x in event.actor_digest)
                or (event.response_ref is not None and not _ref(event.response_ref))
                or type(event.revision) is not int
                or event.revision != (1 if former is None else former.revision + 1)
                or (former is None and (
                    event.stage != REQUESTED or event.response_ref is not None
                ))
                or (former is not None and (
                    former.stage != REQUESTED or event.stage != RESPONDED
                    or event.request_ref != former.request_ref
                    or event.actor_digest == former.actor_digest
                    or event.response_ref is None
                ))
                or canonical(event.payload()) != payload
                or digest(payload) != stamp
            ):
                raise HandoffIntegrityError("enquiry history lineage mismatch")
            events.append(event)
            actions.add(action)
            last[key] = event
            prev = stamp
        if meta["head"] != prev:
            raise HandoffIntegrityError("enquiry chain head mismatch")
        return handoffs, events

    def _append(
        self, *, principal: Principal, domain: str, evidence_id: str,
        check_kind: str, source_action_id: str, action_id: str,
        request_ref: str, response_ref: str | None,
        expected_revision: int, stage: str,
    ) -> AuthorityEnquiryEvent:
        actor = self.handoff._actor(principal, domain)
        if (
            check_kind not in CHECKS or not _ref(action_id)
            or not _ref(source_action_id) or not _ref(request_ref)
            or (response_ref is not None and not _ref(response_ref))
            or type(expected_revision) is not int or expected_revision not in (0, 1)
            or stage not in (REQUESTED, RESPONDED)
            or (stage == REQUESTED and response_ref is not None)
            or (stage == RESPONDED and response_ref is None)
        ):
            raise ValueError("invalid technical verification enquiry")
        verify_pinned_business_sources()
        with self.handoff._transaction() as db:
            handoffs, events = self._verify(db)
            source = next((
                e for e in handoffs if e.domain == domain
                and e.evidence_id == evidence_id
                and e.stage == "REFERENCE_RECORDED"
            ), None)
            if source is None or source.action_id != source_action_id:
                raise HandoffConflict("missing or stale original evidence reference")
            if stage == RESPONDED and not self._response_authorizer(
                principal.subject, domain, evidence_id, check_kind,
            ):
                raise HandoffNotAuthorized("independent response authority missing")
            by_action = next((e for e in events if e.action_id == action_id), None)
            if by_action is not None:
                if (
                    by_action.domain == domain
                    and by_action.evidence_id == evidence_id
                    and by_action.check_kind == check_kind
                    and by_action.stage == stage
                    and by_action.actor_digest == actor
                    and by_action.source_action_id == source_action_id
                    and by_action.source_event_digest == source.event_digest
                    and by_action.request_ref == request_ref
                    and by_action.response_ref == response_ref
                    and by_action.revision == expected_revision + 1
                ):
                    return by_action
                raise HandoffConflict("action ID reused with different input")
            current = next((
                e for e in reversed(events)
                if (e.domain, e.evidence_id, e.check_kind)
                == (domain, evidence_id, check_kind)
            ), None)
            if (
                expected_revision != (current.revision if current else 0)
                or (stage == REQUESTED and current is not None)
                or (stage == RESPONDED and (
                    current is None or current.stage != REQUESTED
                    or current.request_ref != request_ref
                    or current.actor_digest == actor
                ))
            ):
                raise HandoffConflict("unexpected verification enquiry revision")
            sequence = len(events) + 1
            previous = events[-1].event_digest if events else GENESIS
            data = {
                "sequence": sequence, "action_id": action_id,
                "domain": domain, "evidence_id": evidence_id,
                "check_kind": check_kind, "stage": stage,
                "revision": expected_revision + 1, "actor_digest": actor,
                "source_action_id": source.action_id,
                "source_event_digest": source.event_digest,
                "request_ref": request_ref, "response_ref": response_ref,
                "previous_digest": previous,
            }
            serialized = canonical(data)
            stamp = digest(serialized)
            db.execute(
                "INSERT INTO authority_enquiry_event VALUES (?, ?, ?, ?, ?)",
                (sequence, action_id, serialized, stamp, previous),
            )
            db.execute(
                "UPDATE authority_enquiry_meta SET value=? WHERE key='head'",
                (stamp,),
            )
            return AuthorityEnquiryEvent(**data, event_digest=stamp)

    def request_check(
        self, *, principal: Principal, domain: str, evidence_id: str,
        check_kind: str, source_action_id: str, action_id: str,
        request_ref: str, expected_revision: int = 0,
    ) -> AuthorityEnquiryEvent:
        return self._append(
            principal=principal, domain=domain, evidence_id=evidence_id,
            check_kind=check_kind, source_action_id=source_action_id,
            action_id=action_id, request_ref=request_ref, response_ref=None,
            expected_revision=expected_revision, stage=REQUESTED,
        )

    def record_response_reference(
        self, *, principal: Principal, domain: str, evidence_id: str,
        check_kind: str, source_action_id: str, action_id: str,
        request_ref: str, response_ref: str, expected_revision: int = 1,
    ) -> AuthorityEnquiryEvent:
        return self._append(
            principal=principal, domain=domain, evidence_id=evidence_id,
            check_kind=check_kind, source_action_id=source_action_id,
            action_id=action_id, request_ref=request_ref,
            response_ref=response_ref, expected_revision=expected_revision,
            stage=RESPONDED,
        )

    def read_check_status(self, principal: Principal, domain: str) -> dict:
        self.handoff._actor(principal, domain)
        verify_pinned_business_sources()
        with self.handoff._transaction() as db:
            _, events = self._verify(db)
            last = {
                (e.evidence_id, e.check_kind): e
                for e in events if e.domain == domain
            }
            from .business_gate_evidence import DOSSIERS
            dossier = next(d for d in DOSSIERS if d.domain == domain)
            items = []
            for source in dossier.evidence:
                for kind in CHECKS:
                    event = last.get((source.evidence_id, kind))
                    items.append({
                        "evidence_id": source.evidence_id, "check_kind": kind,
                        "technical_state": (
                            event.stage if event else "NO_REQUEST"
                        ),
                        "revision": event.revision if event else 0,
                        "authority_verified": False,
                        "source_rights_verified": False,
                        "reviewer_qualified": False,
                        "business_gate_passed": False,
                        "admission_allowed": False,
                    })
            return {
                "domain": domain,
                "business_source_sha": BUSINESS_SOURCE_SHA,
                "snapshot_state": "PINNED_DRAFT_SNAPSHOT_NOT_LIVE",
                "verification_state": "NO_TRUSTED_EXTERNAL_AUTHORITY",
                "items": items,
            }

    def verify_integrity(self) -> bool:
        from .business_gate_evidence import BusinessSourceSnapshotError
        try:
            verify_pinned_business_sources()
            with self.handoff._transaction() as db:
                self._verify(db)
            return True
        except (HandoffIntegrityError, BusinessSourceSnapshotError, sqlite3.Error):
            return False
