"""PostgreSQL append-only adapter for exact-version producer consent."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row

from .auth import Principal
from .domestic_surplus_drafts import SurplusDraftLedger
from .domestic_surplus_producer_consent import (
    ProducerConsentConflict, ProducerConsentIntegrityError,
    ProducerConsentReceipt, ProducerConsentStorageError, _ACTION,
)
from .domestic_surplus_publication import OfferRevision, PublicationAttestation
from .scoped_drafts import _synthetic_ref


class PostgresSurplusProducerConsentLedger:
    """Encrypted owner-scoped journal with PostgreSQL transaction locks."""

    def __init__(self, dsn: str, draft_ledger: SurplusDraftLedger,
                 encryption_key: bytes, scope_key: bytes, *,
                 connect_timeout: int = 3):
        if (not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn
                or not callable(getattr(draft_ledger, "read_owned", None))
                or not isinstance(encryption_key, bytes) or len(encryption_key) != 32
                or not isinstance(scope_key, bytes) or len(scope_key) != 32
                or type(connect_timeout) is not int or not 1 <= connect_timeout <= 15):
            raise ValueError("PostgreSQL, exact draft ledger, and private keys required")
        self._dsn = dsn
        self._draft_ledger = draft_ledger
        self._cipher = AESGCM(encryption_key)
        self._scope_key = hmac.new(
            scope_key, b"ronas:surplus-producer-consent:scope:v1",
            hashlib.sha256,
        ).digest()
        self._connect_timeout = connect_timeout
        self._initialize()

    def _connect(self):
        return psycopg.connect(
            self._dsn, connect_timeout=self._connect_timeout,
            application_name="ronas-surplus-producer-consent",
            row_factory=dict_row,
        )

    def _initialize(self) -> None:
        try:
            with self._connect() as db:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS ronas_domestic_surplus_producer_consent (
                        action_id TEXT PRIMARY KEY CHECK
                            (action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$'),
                        household_ref TEXT NOT NULL,
                        offer_ref TEXT NOT NULL,
                        producer_hash CHAR(64) NOT NULL CHECK
                            (producer_hash ~ '^[0-9a-f]{64}$'),
                        producer_ciphertext BYTEA NOT NULL CHECK
                            (octet_length(producer_ciphertext) >= 28),
                        offer_revision INTEGER NOT NULL CHECK (offer_revision > 0),
                        payload_digest CHAR(64) NOT NULL CHECK
                            (payload_digest ~ '^[0-9a-f]{64}$'),
                        revision INTEGER NOT NULL CHECK (revision > 0),
                        state TEXT NOT NULL CHECK (state IN ('APPROVED','WITHDRAWN')),
                        previous_digest CHAR(64) NOT NULL CHECK
                            (previous_digest ~ '^[0-9a-f]{64}$'),
                        receipt_digest CHAR(64) NOT NULL UNIQUE CHECK
                            (receipt_digest ~ '^[0-9a-f]{64}$'),
                        UNIQUE (household_ref, offer_ref, offer_revision, revision)
                    )
                """)
                db.execute("""
                    CREATE INDEX IF NOT EXISTS ronas_surplus_consent_current
                    ON ronas_domestic_surplus_producer_consent
                       (household_ref, offer_ref, offer_revision, revision)
                """)
                db.execute("""
                    CREATE OR REPLACE FUNCTION ronas_reject_surplus_consent_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'surplus producer consent history is immutable'; END;
                    $$
                """)
                db.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM pg_trigger
                          WHERE tgname='ronas_surplus_consent_no_update_delete'
                            AND tgrelid='ronas_domestic_surplus_producer_consent'::regclass
                            AND NOT tgisinternal) THEN
                        CREATE TRIGGER ronas_surplus_consent_no_update_delete
                        BEFORE UPDATE OR DELETE ON ronas_domestic_surplus_producer_consent
                        FOR EACH ROW EXECUTE FUNCTION ronas_reject_surplus_consent_mutation();
                      END IF;
                    END $$
                """)
        except psycopg.Error as exc:
            raise ProducerConsentStorageError(
                "producer consent storage unavailable",
            ) from exc

    @staticmethod
    def _hash(body: dict) -> str:
        return hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")).hexdigest()

    @staticmethod
    def _identity(principal: Principal, household_ref: str,
                  offer_ref: str) -> None:
        if (not isinstance(principal, Principal)
                or "household" not in principal.roles
                or not principal.subject or len(principal.subject) > 256
                or not _synthetic_ref(household_ref)
                or not _synthetic_ref(offer_ref)):
            raise LookupError("offer unavailable")

    def _producer_hash(self, subject: str) -> str:
        return hmac.new(
            self._scope_key, subject.encode("utf-8"), hashlib.sha256,
        ).hexdigest()

    def _encrypt_subject(self, subject: str, action_id: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(
            nonce, subject.encode("utf-8"),
            ("surplus-producer-consent:" + action_id).encode("ascii"),
        )

    def _decrypt_subject(self, row) -> str:
        value = row["producer_ciphertext"]
        if isinstance(value, memoryview):
            value = value.tobytes()
        if not isinstance(value, bytes) or len(value) < 28:
            raise ProducerConsentIntegrityError("producer consent integrity failure")
        try:
            subject = self._cipher.decrypt(
                value[:12], value[12:],
                ("surplus-producer-consent:" + row["action_id"]).encode("ascii"),
            ).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise ProducerConsentIntegrityError(
                "producer consent integrity failure",
            ) from exc
        stored_hash = row["producer_hash"].strip()
        if not hmac.compare_digest(self._producer_hash(subject), stored_hash):
            raise ProducerConsentIntegrityError("producer consent integrity failure")
        return subject

    def _chain(self, db, household_ref: str, offer_ref: str,
               offer_revision: int):
        rows = db.execute("""
            SELECT * FROM ronas_domestic_surplus_producer_consent
            WHERE household_ref=%s AND offer_ref=%s AND offer_revision=%s
            ORDER BY revision
        """, (household_ref, offer_ref, offer_revision)).fetchall()
        previous = "0" * 64
        for revision, row in enumerate(rows, 1):
            subject = self._decrypt_subject(row)
            body = {
                "action_id": row["action_id"],
                "household_ref": row["household_ref"],
                "offer_ref": row["offer_ref"],
                "producer_subject": subject,
                "offer_revision": row["offer_revision"],
                "payload_digest": row["payload_digest"].strip(),
                "revision": row["revision"], "state": row["state"],
                "previous_digest": row["previous_digest"].strip(),
            }
            if (row["revision"] != revision
                    or row["previous_digest"].strip() != previous
                    or self._hash(body) != row["receipt_digest"].strip()):
                raise ProducerConsentIntegrityError(
                    "producer consent integrity verification failed",
                )
            previous = row["receipt_digest"].strip()
        return rows

    def _receipt(self, row) -> ProducerConsentReceipt:
        return ProducerConsentReceipt(
            household_ref=row["household_ref"], offer_ref=row["offer_ref"],
            producer_subject=self._decrypt_subject(row),
            offer_revision=row["offer_revision"],
            payload_digest=row["payload_digest"].strip(), revision=row["revision"],
            state=row["state"], action_id=row["action_id"],
            receipt_digest=row["receipt_digest"].strip(),
        )

    def record(self, principal: Principal, household_ref: str, offer_ref: str,
               *, expected_offer_revision: int, expected_payload_digest: str,
               action_id: str, approved: bool) -> ProducerConsentReceipt:
        self._identity(principal, household_ref, offer_ref)
        if (type(expected_offer_revision) is not int or expected_offer_revision < 1
                or not isinstance(expected_payload_digest, str)
                or len(expected_payload_digest) != 64
                or any(char not in "0123456789abcdef" for char in expected_payload_digest)
                or not isinstance(action_id, str) or not _ACTION.fullmatch(action_id)
                or type(approved) is not bool):
            raise ValueError("invalid producer consent command")
        draft = self._draft_ledger.read_owned(principal, household_ref, offer_ref)
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
        try:
            with self._connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           ("ronas-surplus-consent-action:" + action_id,))
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           ("ronas-surplus-consent-offer:" + json.dumps(
                               [household_ref, offer_ref, expected_offer_revision],
                               separators=(",", ":"),
                           ),))
                replay = db.execute("""
                    SELECT * FROM ronas_domestic_surplus_producer_consent
                    WHERE action_id=%s
                """, (action_id,)).fetchone()
                if replay is not None:
                    rows = self._chain(
                        db, replay["household_ref"], replay["offer_ref"],
                        replay["offer_revision"],
                    )
                    replay_command = {
                        "household_ref": replay["household_ref"],
                        "offer_ref": replay["offer_ref"],
                        "producer_subject": self._decrypt_subject(replay),
                        "offer_revision": replay["offer_revision"],
                        "payload_digest": replay["payload_digest"].strip(),
                        "state": replay["state"], "action_id": replay["action_id"],
                    }
                    if (self._hash(command) != self._hash(replay_command)
                            or not rows or replay["receipt_digest"].strip()
                            not in {row["receipt_digest"].strip() for row in rows}):
                        raise ProducerConsentConflict("consent action replay differs")
                    return self._receipt(replay)
                rows = self._chain(
                    db, household_ref, offer_ref, expected_offer_revision,
                )
                revision = len(rows) + 1
                previous = rows[-1]["receipt_digest"].strip() if rows else "0" * 64
                body = {**command, "revision": revision,
                        "previous_digest": previous}
                receipt_digest = self._hash(body)
                row = db.execute("""
                    INSERT INTO ronas_domestic_surplus_producer_consent
                    (action_id,household_ref,offer_ref,producer_hash,
                     producer_ciphertext,offer_revision,payload_digest,revision,
                     state,previous_digest,receipt_digest)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                """, (
                    action_id, household_ref, offer_ref,
                    self._producer_hash(principal.subject),
                    self._encrypt_subject(principal.subject, action_id),
                    expected_offer_revision, expected_payload_digest, revision,
                    state, previous, receipt_digest,
                )).fetchone()
                return self._receipt(row)
        except (ProducerConsentConflict, ProducerConsentIntegrityError, LookupError, ValueError):
            raise
        except psycopg.Error as exc:
            raise ProducerConsentStorageError(
                "producer consent write failed",
            ) from exc

    def current(self, principal: Principal, household_ref: str,
                offer_ref: str) -> ProducerConsentReceipt | None:
        self._identity(principal, household_ref, offer_ref)
        try:
            draft = self._draft_ledger.read_owned(principal, household_ref, offer_ref)
            if draft.producer_subject != principal.subject:
                raise LookupError("offer unavailable")
            with self._connect() as db:
                rows = self._chain(db, household_ref, offer_ref, draft.revision)
            if not rows:
                return None
            receipt = self._receipt(rows[-1])
            if receipt.producer_subject != principal.subject:
                raise ProducerConsentIntegrityError("producer consent owner mismatch")
            return receipt
        except (ProducerConsentIntegrityError, LookupError, RuntimeError, ValueError):
            raise
        except psycopg.Error as exc:
            raise ProducerConsentStorageError(
                "producer consent read failed",
            ) from exc

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
