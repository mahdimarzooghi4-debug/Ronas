"""Encrypted PostgreSQL adapter for private Domestic surplus draft revisions.

The adapter implements the same append-only interface as the LOCAL SQLite
ledger. It is opt-in; selecting it never opens a listing or publishes an offer.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row

from .auth import Principal
from .domestic_surplus_drafts import (
    SurplusDraftConflict, SurplusDraftIntegrityError, SurplusDraftRevision,
    SurplusDraftStorageError, _ACTION,
)
from .household_input_profiles import HouseholdInputSchema
from .scoped_drafts import _synthetic_ref


def surplus_offer_lock_key(household_ref: str, offer_ref: str) -> str:
    """Shared transaction-lock namespace for offer edits and consent writes."""
    return "ronas-surplus-offer:" + json.dumps(
        [household_ref, offer_ref], separators=(",", ":"),
    )


class PostgresSurplusDraftLedger:
    """Encrypted owner-scoped draft journal with per-offer serialization."""

    def __init__(self, dsn: str, schema: HouseholdInputSchema,
                 owner_access_authority, encryption_key: bytes,
                 scope_key: bytes, *, connect_timeout: int = 3):
        if (not isinstance(dsn, str) or not dsn or len(dsn) > 4096 or "\x00" in dsn
                or not isinstance(schema, HouseholdInputSchema)
                or not callable(owner_access_authority)
                or not isinstance(encryption_key, bytes) or len(encryption_key) != 32
                or not isinstance(scope_key, bytes) or len(scope_key) != 32
                or type(connect_timeout) is not int or not 1 <= connect_timeout <= 15):
            raise ValueError("valid PostgreSQL, schema, authority, and key configuration required")
        self._dsn = dsn
        self.schema = schema
        self._owner_access_authority = owner_access_authority
        self._cipher = AESGCM(encryption_key)
        self._scope_key = hmac.new(
            scope_key, b"ronas:surplus-draft:scope:v1", hashlib.sha256,
        ).digest()
        self._connect_timeout = connect_timeout
        self._initialize()

    def _connect(self):
        return psycopg.connect(
            self._dsn, connect_timeout=self._connect_timeout,
            application_name="ronas-surplus-draft",
            row_factory=dict_row,
        )

    def _initialize(self) -> None:
        try:
            with self._connect() as db:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS ronas_domestic_surplus_draft_revision (
                        action_id TEXT PRIMARY KEY CHECK (action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$'),
                        household_ref TEXT NOT NULL,
                        offer_ref TEXT NOT NULL,
                        owner_hash CHAR(64) NOT NULL CHECK (owner_hash ~ '^[0-9a-f]{64}$'),
                        owner_ciphertext BYTEA NOT NULL CHECK (octet_length(owner_ciphertext) >= 28),
                        schema_ref TEXT NOT NULL,
                        schema_version INTEGER NOT NULL CHECK (schema_version > 0),
                        schema_digest CHAR(64) NOT NULL CHECK (schema_digest ~ '^[0-9a-f]{64}$'),
                        revision INTEGER NOT NULL CHECK (revision > 0),
                        input_revision INTEGER CHECK (input_revision IS NULL OR input_revision > 0),
                        values_ciphertext BYTEA NOT NULL
                            CHECK (octet_length(values_ciphertext) BETWEEN 29 AND 65564),
                        command_digest CHAR(64) NOT NULL CHECK (command_digest ~ '^[0-9a-f]{64}$'),
                        payload_digest CHAR(64) NOT NULL CHECK (payload_digest ~ '^[0-9a-f]{64}$'),
                        previous_receipt_digest CHAR(64) NOT NULL CHECK (previous_receipt_digest ~ '^[0-9a-f]{64}$'),
                        receipt_digest CHAR(64) NOT NULL UNIQUE CHECK (receipt_digest ~ '^[0-9a-f]{64}$'),
                        UNIQUE (household_ref, offer_ref, revision)
                    )
                """)
                db.execute("""
                    CREATE INDEX IF NOT EXISTS ronas_surplus_draft_lookup
                    ON ronas_domestic_surplus_draft_revision(household_ref, offer_ref, revision)
                """)
                db.execute("""
                    ALTER TABLE ronas_domestic_surplus_draft_revision
                    ADD COLUMN IF NOT EXISTS input_revision INTEGER
                    CHECK (input_revision IS NULL OR input_revision > 0)
                """)
                db.execute("""
                    CREATE OR REPLACE FUNCTION ronas_reject_surplus_draft_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'surplus draft history is immutable'; END;
                    $$
                """)
                db.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM pg_trigger
                          WHERE tgname='ronas_surplus_draft_no_update'
                            AND tgrelid='ronas_domestic_surplus_draft_revision'::regclass
                            AND NOT tgisinternal) THEN
                        CREATE TRIGGER ronas_surplus_draft_no_update
                        BEFORE UPDATE OR DELETE ON ronas_domestic_surplus_draft_revision
                        FOR EACH ROW EXECUTE FUNCTION ronas_reject_surplus_draft_mutation();
                      END IF;
                    END $$
                """)
        except psycopg.Error as exc:
            raise SurplusDraftStorageError("surplus draft storage unavailable") from exc

    @staticmethod
    def _hash(body) -> str:
        canonical = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _owner(self, principal, household_ref: str, offer_ref: str) -> str:
        if (not isinstance(principal, Principal) or "household" not in principal.roles
                or not _synthetic_ref(household_ref) or not _synthetic_ref(offer_ref)
                or not principal.subject or len(principal.subject) > 256):
            raise LookupError("draft unavailable")
        try:
            permitted = self._owner_access_authority(
                principal, household_ref, self.schema.schema_ref,
            )
        except Exception as exc:
            raise RuntimeError("household owner authority unavailable") from exc
        if permitted is not True:
            raise LookupError("draft unavailable")
        return principal.subject

    def _owner_hash(self, owner: str) -> str:
        return hmac.new(self._scope_key, owner.encode("utf-8"), hashlib.sha256).hexdigest()

    def _encrypt_owner(self, owner: str, action_id: str) -> bytes:
        import secrets
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(
            nonce, owner.encode("utf-8"), ("surplus-owner:" + action_id).encode("ascii"),
        )

    def _values_aad(self, row_or_owner_hash: str, household_ref: str,
                    offer_ref: str, revision: int) -> bytes:
        return ("surplus-values:" + row_or_owner_hash + ":" + household_ref
                + ":" + offer_ref + ":" + str(revision)).encode("utf-8")

    def _encrypt_values(self, owner_hash: str, household_ref: str,
                        offer_ref: str, revision: int, values: dict[str, str]) -> bytes:
        import secrets
        plaintext = json.dumps(
            values, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        if len(plaintext) > 65536:
            raise ValueError("surplus draft values exceed technical limit")
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(
            nonce, plaintext,
            self._values_aad(owner_hash, household_ref, offer_ref, revision),
        )

    def _decrypt_owner(self, row) -> str:
        value = row["owner_ciphertext"]
        if isinstance(value, memoryview):
            value = value.tobytes()
        if not isinstance(value, bytes) or len(value) < 28:
            raise SurplusDraftIntegrityError("surplus draft owner integrity failure")
        try:
            owner = self._cipher.decrypt(
                value[:12], value[12:],
                ("surplus-owner:" + row["action_id"]).encode("ascii"),
            ).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise SurplusDraftIntegrityError("surplus draft owner integrity failure") from exc
        if not hmac.compare_digest(self._owner_hash(owner), row["owner_hash"].strip()):
            raise SurplusDraftIntegrityError("surplus draft owner integrity failure")
        return owner

    def _values(self, row) -> dict[str, str]:
        ciphertext = row["values_ciphertext"]
        if isinstance(ciphertext, memoryview):
            ciphertext = ciphertext.tobytes()
        if not isinstance(ciphertext, bytes) or len(ciphertext) < 29:
            raise SurplusDraftIntegrityError("surplus draft values integrity failure")
        try:
            plaintext = self._cipher.decrypt(
                ciphertext[:12], ciphertext[12:],
                self._values_aad(
                    row["owner_hash"].strip(), row["household_ref"],
                    row["offer_ref"], row["revision"],
                ),
            )
            values = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise SurplusDraftIntegrityError("surplus draft values integrity failure") from exc
        if not isinstance(values, dict) or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in values.items()):
            raise SurplusDraftIntegrityError("surplus draft values integrity failure")
        return values

    def _verify_chain(self, rows) -> None:
        previous = "0" * 64
        owner = household = offer = None
        for index, row in enumerate(rows, 1):
            actual_owner = self._decrypt_owner(row)
            values = self._values(row)
            if (row["revision"] != index or row["previous_receipt_digest"].strip() != previous
                    or owner is not None and actual_owner != owner
                    or household is not None and row["household_ref"] != household
                    or offer is not None and row["offer_ref"] != offer):
                raise SurplusDraftIntegrityError("surplus draft receipt chain failure")
            owner, household, offer = actual_owner, row["household_ref"], row["offer_ref"]
            schema_digest = row["schema_digest"].strip()
            payload = self._hash({"schema_digest": schema_digest, "values": values})
            command = self._hash({
                "owner": owner, "household_ref": household, "offer_ref": offer,
                "action_id": row["action_id"], "expected_revision": index - 1,
                "schema_digest": schema_digest, "values": values,
                **({"input_revision": row["input_revision"]}
                   if row.get("input_revision") is not None else {}),
            })
            receipt = self._hash({
                "household_ref": household, "offer_ref": offer,
                "producer_subject": owner, "schema_ref": row["schema_ref"],
                "schema_version": row["schema_version"], "schema_digest": schema_digest,
                "revision": index, "values": values, "payload_digest": payload,
                "previous_receipt_digest": previous,
                **({"input_revision": row["input_revision"]}
                   if row.get("input_revision") is not None else {}),
            })
            if (payload != row["payload_digest"].strip()
                    or command != row["command_digest"].strip()
                    or receipt != row["receipt_digest"].strip()):
                raise SurplusDraftIntegrityError("surplus draft receipt chain failure")
            previous = receipt

    def _decode(self, row) -> SurplusDraftRevision:
        return SurplusDraftRevision(
            household_ref=row["household_ref"], offer_ref=row["offer_ref"],
            producer_subject=row["decoded_owner"], schema_ref=row["schema_ref"],
            schema_version=row["schema_version"], schema_digest=row["schema_digest"].strip(),
            revision=row["revision"], values=self._values(row),
            payload_digest=row["payload_digest"].strip(),
            previous_receipt_digest=row["previous_receipt_digest"].strip(),
            receipt_digest=row["receipt_digest"].strip(),
            input_revision=row.get("input_revision"),
        )

    def _decode_rows(self, rows):
        self._verify_chain(rows)
        records = []
        for row in rows:
            enriched = dict(row)
            enriched["decoded_owner"] = self._decrypt_owner(row)
            records.append(self._decode(enriched))
        return tuple(records)

    def save(self, principal, household_ref, offer_ref, *, action_id,
             expected_revision, values, input_revision=None):
        owner = self._owner(principal, household_ref, offer_ref)
        if (not isinstance(action_id, str) or not _ACTION.fullmatch(action_id)
                or type(expected_revision) is not int or expected_revision < 0
                or (input_revision is not None and
                    (type(input_revision) is not int or input_revision < 1))):
            raise ValueError("invalid surplus draft command")
        normalized = self.schema.validate(values)
        payload_digest = self._hash({"schema_digest": self.schema.digest, "values": normalized})
        command_digest = self._hash({
            "owner": owner, "household_ref": household_ref, "offer_ref": offer_ref,
            "action_id": action_id, "expected_revision": expected_revision,
            "schema_digest": self.schema.digest, "values": normalized,
            **({"input_revision": input_revision}
               if input_revision is not None else {}),
        })
        owner_hash = self._owner_hash(owner)
        try:
            with self._connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           ("ronas-surplus-action:" + action_id,))
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           (surplus_offer_lock_key(household_ref, offer_ref),))
                replay = db.execute(
                    "SELECT * FROM ronas_domestic_surplus_draft_revision WHERE action_id=%s",
                    (action_id,),
                ).fetchone()
                if replay is not None:
                    rows = db.execute("""SELECT * FROM ronas_domestic_surplus_draft_revision
                        WHERE household_ref=%s AND offer_ref=%s ORDER BY revision""",
                        (replay["household_ref"], replay["offer_ref"])).fetchall()
                    self._verify_chain(rows)
                    if replay["command_digest"].strip() != command_digest:
                        raise SurplusDraftConflict("action reference replay differs")
                    if not hmac.compare_digest(replay["owner_hash"].strip(), owner_hash):
                        raise LookupError("draft unavailable")
                    enriched = dict(replay); enriched["decoded_owner"] = self._decrypt_owner(replay)
                    return self._decode(enriched)
                rows = db.execute("""SELECT * FROM ronas_domestic_surplus_draft_revision
                    WHERE household_ref=%s AND offer_ref=%s ORDER BY revision""",
                    (household_ref, offer_ref)).fetchall()
                self._verify_chain(rows)
                latest = rows[-1] if rows else None
                revision = 0 if latest is None else latest["revision"]
                if latest is not None and not hmac.compare_digest(
                        latest["owner_hash"].strip(), owner_hash):
                    raise LookupError("draft unavailable")
                if expected_revision != revision:
                    raise SurplusDraftConflict("surplus draft revision is stale")
                revision += 1
                previous = "0" * 64 if latest is None else latest["receipt_digest"].strip()
                receipt = self._hash({
                    "household_ref": household_ref, "offer_ref": offer_ref,
                    "producer_subject": owner, "schema_ref": self.schema.schema_ref,
                    "schema_version": self.schema.version, "schema_digest": self.schema.digest,
                    "revision": revision, "values": normalized,
                    "payload_digest": payload_digest, "previous_receipt_digest": previous,
                    **({"input_revision": input_revision}
                       if input_revision is not None else {}),
                })
                inserted = db.execute("""INSERT INTO ronas_domestic_surplus_draft_revision
                    (action_id,household_ref,offer_ref,owner_hash,owner_ciphertext,
                     schema_ref,schema_version,schema_digest,revision,input_revision,values_ciphertext,
                     command_digest,payload_digest,previous_receipt_digest,receipt_digest)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (action_id, household_ref, offer_ref, owner_hash,
                     self._encrypt_owner(owner, action_id), self.schema.schema_ref,
                     self.schema.version, self.schema.digest, revision, input_revision,
                     self._encrypt_values(
                         owner_hash, household_ref, offer_ref, revision, normalized,
                     ),
                     command_digest, payload_digest, previous, receipt)).fetchone()
                result = dict(inserted); result["decoded_owner"] = owner
                return self._decode(result)
        except (SurplusDraftConflict, SurplusDraftIntegrityError, LookupError, ValueError):
            raise
        except psycopg.Error as exc:
            raise SurplusDraftStorageError("surplus draft write failed") from exc

    def _chain(self, principal, household_ref, offer_ref):
        owner = self._owner(principal, household_ref, offer_ref)
        try:
            with self._connect() as db:
                rows = db.execute("""SELECT * FROM ronas_domestic_surplus_draft_revision
                    WHERE household_ref=%s AND offer_ref=%s ORDER BY revision""",
                    (household_ref, offer_ref)).fetchall()
        except psycopg.Error as exc:
            raise SurplusDraftStorageError("surplus draft read failed") from exc
        if not rows:
            raise LookupError("draft unavailable")
        records = self._decode_rows(rows)
        if records[-1].producer_subject != owner:
            raise LookupError("draft unavailable")
        return records

    def history_owned(self, principal, household_ref, offer_ref):
        return self._chain(principal, household_ref, offer_ref)

    def read_owned(self, principal, household_ref, offer_ref):
        return self._chain(principal, household_ref, offer_ref)[-1]

    def list_owned(self, principal, household_ref):
        owner = self._owner(principal, household_ref, "DEMO-OFFER-LIST")
        try:
            with self._connect() as db:
                rows = db.execute("""SELECT * FROM ronas_domestic_surplus_draft_revision
                    WHERE household_ref=%s ORDER BY offer_ref,revision""",
                    (household_ref,)).fetchall()
        except psycopg.Error as exc:
            raise SurplusDraftStorageError("surplus draft list failed") from exc
        grouped = {}
        for row in rows:
            grouped.setdefault(row["offer_ref"], []).append(row)
        result = []
        for chain in grouped.values():
            records = self._decode_rows(chain)
            if records[-1].producer_subject != owner:
                raise SurplusDraftIntegrityError("draft owner does not match authorized household")
            result.append(records[-1])
        return tuple(sorted(result, key=lambda item: item.offer_ref))
