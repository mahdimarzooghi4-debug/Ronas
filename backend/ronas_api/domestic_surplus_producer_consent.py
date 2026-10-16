"""Append-only LOCAL/TEST household consent for one exact surplus revision.

This ledger records the producer's explicit decision to allow or withdraw a
publication approval for the exact current draft. It never publishes a listing
and does not replace the independent quality/safety authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3

from .auth import Principal
from .domestic_surplus_publication import (
    OfferRevision, PublicationAttestation,
)
from .domestic_surplus_drafts import (
    SurplusDraftLedger, is_surplus_draft_ledger,
)
from .scoped_drafts import _synthetic_ref

_ACTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")


class ProducerConsentConflict(ValueError):
    """The offer version or consent action changed."""


class ProducerConsentIntegrityError(RuntimeError):
    """The append-only consent chain failed verification."""


@dataclass(frozen=True, slots=True)
class ProducerConsentReceipt:
    household_ref: str
    offer_ref: str
    producer_subject: str
    offer_revision: int
    payload_digest: str
    revision: int
    state: str
    action_id: str
    receipt_digest: str


class SqliteSyntheticProducerConsentLedger:
    """Owner-scoped consent journal for explicit LOCAL/TEST DEMO offers."""

    def __init__(self, database_path: str, draft_ledger: SurplusDraftLedger):
        if (not isinstance(database_path, str) or not database_path
                or not is_surplus_draft_ledger(draft_ledger)):
            raise ValueError("private database path and surplus draft ledger required")
        self._database_path = database_path
        self._draft_ledger = draft_ledger
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS domestic_surplus_producer_consent (
                    action_id TEXT PRIMARY KEY,
                    household_ref TEXT NOT NULL,
                    offer_ref TEXT NOT NULL,
                    producer_subject TEXT NOT NULL,
                    offer_revision INTEGER NOT NULL CHECK (offer_revision > 0),
                    payload_digest TEXT NOT NULL CHECK (length(payload_digest)=64),
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    state TEXT NOT NULL CHECK (state IN ('APPROVED','WITHDRAWN')),
                    previous_digest TEXT NOT NULL CHECK (length(previous_digest)=64),
                    receipt_digest TEXT NOT NULL UNIQUE CHECK (length(receipt_digest)=64),
                    UNIQUE(household_ref,offer_ref,offer_revision,revision)
                );
                CREATE TRIGGER IF NOT EXISTS producer_consent_no_update
                BEFORE UPDATE ON domestic_surplus_producer_consent
                BEGIN SELECT RAISE(ABORT, 'producer consent history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS producer_consent_no_delete
                BEFORE DELETE ON domestic_surplus_producer_consent
                BEGIN SELECT RAISE(ABORT, 'producer consent history immutable'); END;
                CREATE INDEX IF NOT EXISTS producer_consent_current
                ON domestic_surplus_producer_consent(household_ref,offer_ref,
                   offer_revision,revision);
            """)

    def _connect(self):
        db = sqlite3.connect(self._database_path, timeout=5,
                             isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @staticmethod
    def _hash(value: dict) -> str:
        return hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")).hexdigest()

    @staticmethod
    def _identity(principal: Principal, household_ref: str,
                  offer_ref: str) -> None:
        if (not isinstance(principal, Principal)
                or "household" not in principal.roles
                or not _synthetic_ref(household_ref)
                or not _synthetic_ref(offer_ref)):
            raise LookupError("offer unavailable")

    def _chain(self, db, household_ref: str, offer_ref: str,
               offer_revision: int):
        rows = db.execute(
            "SELECT * FROM domestic_surplus_producer_consent "
            "WHERE household_ref=? AND offer_ref=? AND offer_revision=? "
            "ORDER BY revision", (household_ref, offer_ref, offer_revision),
        ).fetchall()
        previous = "0" * 64
        for revision, row in enumerate(rows, 1):
            body = {
                "action_id": row["action_id"],
                "household_ref": row["household_ref"],
                "offer_ref": row["offer_ref"],
                "producer_subject": row["producer_subject"],
                "offer_revision": row["offer_revision"],
                "payload_digest": row["payload_digest"],
                "revision": row["revision"], "state": row["state"],
                "previous_digest": row["previous_digest"],
            }
            if (row["revision"] != revision
                    or row["previous_digest"] != previous
                    or self._hash(body) != row["receipt_digest"]):
                raise ProducerConsentIntegrityError(
                    "producer consent integrity verification failed"
                )
            previous = row["receipt_digest"]
        return rows

    @staticmethod
    def _receipt(row) -> ProducerConsentReceipt:
        return ProducerConsentReceipt(
            household_ref=row["household_ref"], offer_ref=row["offer_ref"],
            producer_subject=row["producer_subject"],
            offer_revision=row["offer_revision"],
            payload_digest=row["payload_digest"], revision=row["revision"],
            state=row["state"], action_id=row["action_id"],
            receipt_digest=row["receipt_digest"],
        )

    def record(self, principal: Principal, household_ref: str, offer_ref: str,
               *, expected_offer_revision: int, expected_payload_digest: str,
               action_id: str, approved: bool) -> ProducerConsentReceipt:
        self._identity(principal, household_ref, offer_ref)
        if (type(expected_offer_revision) is not int or expected_offer_revision < 1
                or not isinstance(expected_payload_digest, str)
                or len(expected_payload_digest) != 64
                or any(c not in "0123456789abcdef" for c in expected_payload_digest)
                or not isinstance(action_id, str) or not _ACTION.fullmatch(action_id)
                or type(approved) is not bool):
            raise ValueError("invalid producer consent command")
        try:
            draft = self._draft_ledger.read_owned(
                principal, household_ref, offer_ref,
            )
        except (LookupError, RuntimeError):
            raise
        if (draft.producer_subject != principal.subject
                or draft.revision != expected_offer_revision
                or draft.payload_digest != expected_payload_digest
                or draft.schema_digest != self._draft_ledger.schema.digest):
            raise ProducerConsentConflict("offer changed before consent")
        state = "APPROVED" if approved else "WITHDRAWN"
        command = {
            "household_ref": household_ref, "offer_ref": offer_ref,
            "producer_subject": principal.subject,
            "offer_revision": expected_offer_revision,
            "payload_digest": expected_payload_digest,
            "state": state, "action_id": action_id,
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                "SELECT * FROM domestic_surplus_producer_consent WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if replay is not None:
                rows = self._chain(
                    db, household_ref, offer_ref, expected_offer_revision,
                )
                if self._hash(command) != self._hash({
                    "household_ref": replay["household_ref"],
                    "offer_ref": replay["offer_ref"],
                    "producer_subject": replay["producer_subject"],
                    "offer_revision": replay["offer_revision"],
                    "payload_digest": replay["payload_digest"],
                    "state": replay["state"], "action_id": replay["action_id"],
                }) or not rows or replay["receipt_digest"] not in {
                        row["receipt_digest"] for row in rows}:
                    raise ProducerConsentConflict("consent action replay differs")
                db.commit()
                return self._receipt(replay)
            rows = self._chain(
                db, household_ref, offer_ref, expected_offer_revision,
            )
            revision = len(rows) + 1
            previous = rows[-1]["receipt_digest"] if rows else "0" * 64
            body = {
                **command, "revision": revision,
                "previous_digest": previous,
            }
            receipt = self._hash(body)
            db.execute(
                "INSERT INTO domestic_surplus_producer_consent "
                "(action_id,household_ref,offer_ref,producer_subject,"
                "offer_revision,payload_digest,revision,state,previous_digest,"
                "receipt_digest) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (action_id, household_ref, offer_ref, principal.subject,
                 expected_offer_revision, expected_payload_digest, revision,
                 state, previous, receipt),
            )
            db.commit()
            return ProducerConsentReceipt(
                household_ref, offer_ref, principal.subject,
                expected_offer_revision, expected_payload_digest,
                revision, state, action_id, receipt,
            )

    def current(self, principal: Principal, household_ref: str,
                offer_ref: str) -> ProducerConsentReceipt | None:
        self._identity(principal, household_ref, offer_ref)
        draft = self._draft_ledger.read_owned(principal, household_ref, offer_ref)
        if draft.producer_subject != principal.subject:
            raise LookupError("offer unavailable")
        with self._connect() as db:
            rows = self._chain(
                db, household_ref, offer_ref, draft.revision,
            )
        return self._receipt(rows[-1]) if rows else None

    def publication_attestation(
        self, principal: Principal, offer: OfferRevision,
    ) -> PublicationAttestation | None:
        receipt = self.current(principal, offer.household_ref, offer.offer_ref)
        if (receipt is None or receipt.state != "APPROVED"
                or receipt.producer_subject != offer.producer_subject
                or receipt.offer_revision != offer.revision
                or receipt.payload_digest != offer.payload_digest):
            return None
        return PublicationAttestation(
            attestation_ref=receipt.action_id,
            offer_ref=offer.offer_ref, offer_revision=offer.revision,
            payload_digest=offer.payload_digest, authority_kind="PRODUCER",
            authority_subject=offer.producer_subject,
            evidence_digest=receipt.receipt_digest, accepted=True,
            authority_verified=True,
        )
