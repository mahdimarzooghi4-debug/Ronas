"""Owner-scoped, schema-driven private Domestic surplus drafts (LOCAL/TEST)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from typing import Any

from .auth import Principal
from .household_input_profiles import HouseholdInputSchema
from .scoped_drafts import _synthetic_ref

_ACTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")


class SurplusDraftConflict(ValueError):
    """The draft revision or idempotency command no longer matches."""


class SurplusDraftIntegrityError(RuntimeError):
    """Stored surplus history no longer matches its immutable receipt chain."""


@dataclass(frozen=True, slots=True)
class SurplusDraftRevision:
    household_ref: str
    offer_ref: str
    producer_subject: str
    schema_ref: str
    schema_version: int
    schema_digest: str
    revision: int
    values: dict[str, str]
    payload_digest: str
    previous_receipt_digest: str
    receipt_digest: str
    published: bool = False
    real_data: bool = False


class SqliteSyntheticSurplusDraftLedger:
    """Append-only local/test draft journal with owner-bound compare-and-swap."""

    def __init__(
        self, database_path: str, schema: HouseholdInputSchema,
        owner_access_authority: Callable[[Principal, str, str], bool],
    ):
        if (not isinstance(database_path, str) or not database_path
                or not isinstance(schema, HouseholdInputSchema)
                or not callable(owner_access_authority)):
            raise ValueError("database path, injected product schema, and owner authority required")
        self._database_path = database_path
        self.schema = schema
        self._owner_access_authority = owner_access_authority
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS domestic_surplus_draft_revision (
                    action_id TEXT PRIMARY KEY,
                    household_ref TEXT NOT NULL,
                    offer_ref TEXT NOT NULL,
                    producer_subject TEXT NOT NULL,
                    schema_ref TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    schema_digest TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    values_json TEXT NOT NULL,
                    command_digest TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    previous_receipt_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    UNIQUE(household_ref, offer_ref, revision)
                );
                CREATE TRIGGER IF NOT EXISTS surplus_draft_revision_no_update
                BEFORE UPDATE ON domestic_surplus_draft_revision
                BEGIN SELECT RAISE(ABORT, 'surplus draft history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS surplus_draft_revision_no_delete
                BEFORE DELETE ON domestic_surplus_draft_revision
                BEGIN SELECT RAISE(ABORT, 'surplus draft history immutable'); END;
                CREATE INDEX IF NOT EXISTS surplus_draft_owner_lookup
                ON domestic_surplus_draft_revision(household_ref, offer_ref, revision);
            """)

    def _connect(self):
        db = sqlite3.connect(self._database_path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @staticmethod
    def _hash(body: Any) -> str:
        canonical = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _household_owner(principal: Any, household_ref: str) -> str:
        from .auth import Principal
        if (not isinstance(principal, Principal)
                or "household" not in principal.roles
                or not _synthetic_ref(household_ref)
                or not principal.subject or len(principal.subject) > 256):
            raise LookupError("draft unavailable")
        return principal.subject

    @classmethod
    def _owner(cls, principal: Any, household_ref: str, offer_ref: str) -> str:
        owner = cls._household_owner(principal, household_ref)
        if not _synthetic_ref(offer_ref):
            raise LookupError("draft unavailable")
        return owner

    def _authorized_owner(self, principal: Any, household_ref: str,
                          offer_ref: str) -> str:
        owner = self._owner(principal, household_ref, offer_ref)
        try:
            permitted = self._owner_access_authority(
                principal, household_ref, self.schema.schema_ref,
            )
        except Exception as exc:
            raise RuntimeError("household owner authority unavailable") from exc
        if permitted is not True:
            raise LookupError("draft unavailable")
        return owner

    @classmethod
    def _verify_chain(cls, rows: list[sqlite3.Row]) -> None:
        previous = "0" * 64
        owner = household = offer = None
        for expected_revision, row in enumerate(rows, start=1):
            try:
                values = json.loads(row["values_json"])
                if (not isinstance(values, dict)
                        or any(not isinstance(key, str) or not isinstance(value, str)
                               for key, value in values.items())
                        or row["revision"] != expected_revision
                        or row["previous_receipt_digest"] != previous):
                    raise ValueError
                if owner is None:
                    owner = row["producer_subject"]
                    household = row["household_ref"]
                    offer = row["offer_ref"]
                elif (row["producer_subject"] != owner
                      or row["household_ref"] != household
                      or row["offer_ref"] != offer):
                    raise ValueError
                payload_digest = cls._hash({
                    "schema_digest": row["schema_digest"], "values": values,
                })
                command_digest = cls._hash({
                    "owner": row["producer_subject"],
                    "household_ref": row["household_ref"],
                    "offer_ref": row["offer_ref"],
                    "action_id": row["action_id"],
                    "expected_revision": row["revision"] - 1,
                    "schema_digest": row["schema_digest"], "values": values,
                })
                body = {
                    "household_ref": row["household_ref"],
                    "offer_ref": row["offer_ref"],
                    "producer_subject": row["producer_subject"],
                    "schema_ref": row["schema_ref"],
                    "schema_version": row["schema_version"],
                    "schema_digest": row["schema_digest"],
                    "revision": row["revision"], "values": values,
                    "payload_digest": payload_digest,
                    "previous_receipt_digest": previous,
                }
                receipt_digest = cls._hash(body)
                if (row["payload_digest"] != payload_digest
                        or row["command_digest"] != command_digest
                        or row["receipt_digest"] != receipt_digest):
                    raise ValueError
                previous = receipt_digest
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise SurplusDraftIntegrityError(
                    "surplus draft integrity verification failed"
                ) from exc

    @staticmethod
    def _chain_rows(db: sqlite3.Connection, household_ref: str,
                    offer_ref: str) -> list[sqlite3.Row]:
        return db.execute(
            """SELECT * FROM domestic_surplus_draft_revision
               WHERE household_ref=? AND offer_ref=? ORDER BY revision""",
            (household_ref, offer_ref),
        ).fetchall()

    def save(
        self, principal: Any, household_ref: str, offer_ref: str, *,
        action_id: str, expected_revision: int, values: dict[str, str],
    ) -> SurplusDraftRevision:
        owner = self._authorized_owner(principal, household_ref, offer_ref)
        if (not isinstance(action_id, str) or not _ACTION.fullmatch(action_id)
                or type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("invalid surplus draft command")
        normalized = self.schema.validate(values)
        values_json = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        payload_digest = self._hash({
            "schema_digest": self.schema.digest, "values": normalized,
        })
        command_digest = self._hash({
            "owner": owner, "household_ref": household_ref, "offer_ref": offer_ref,
            "action_id": action_id, "expected_revision": expected_revision,
            "schema_digest": self.schema.digest, "values": normalized,
        })
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                "SELECT * FROM domestic_surplus_draft_revision WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if replay is not None:
                replay_rows = self._chain_rows(
                    db, replay["household_ref"], replay["offer_ref"],
                )
                self._verify_chain(replay_rows)
                if replay["command_digest"] != command_digest:
                    raise SurplusDraftConflict("action reference replay differs")
                if replay["producer_subject"] != owner:
                    raise LookupError("draft unavailable")
                return self._decode(replay)
            rows = self._chain_rows(db, household_ref, offer_ref)
            self._verify_chain(rows)
            latest = None if not rows else rows[-1]
            current_revision = 0 if latest is None else latest["revision"]
            if latest is not None and latest["producer_subject"] != owner:
                raise LookupError("draft unavailable")
            if expected_revision != current_revision:
                raise SurplusDraftConflict("surplus draft revision is stale")
            revision = current_revision + 1
            previous = "0" * 64 if latest is None else latest["receipt_digest"]
            body = {
                "household_ref": household_ref, "offer_ref": offer_ref,
                "producer_subject": owner, "schema_ref": self.schema.schema_ref,
                "schema_version": self.schema.version, "schema_digest": self.schema.digest,
                "revision": revision, "values": normalized,
                "payload_digest": payload_digest, "previous_receipt_digest": previous,
            }
            receipt = self._hash(body)
            db.execute(
                """INSERT INTO domestic_surplus_draft_revision
                   (action_id,household_ref,offer_ref,producer_subject,schema_ref,
                    schema_version,schema_digest,revision,values_json,command_digest,
                    payload_digest,previous_receipt_digest,receipt_digest)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (action_id, household_ref, offer_ref, owner, self.schema.schema_ref,
                 self.schema.version, self.schema.digest, revision, values_json,
                 command_digest, payload_digest, previous, receipt),
            )
            row = db.execute(
                "SELECT * FROM domestic_surplus_draft_revision WHERE action_id=?",
                (action_id,),
            ).fetchone()
            db.commit()
            return self._decode(row)

    def list_owned(
        self, principal: Any, household_ref: str,
    ) -> tuple[SurplusDraftRevision, ...]:
        """Return current private drafts for one authorized synthetic household."""
        owner = self._household_owner(principal, household_ref)
        try:
            permitted = self._owner_access_authority(
                principal, household_ref, self.schema.schema_ref,
            )
        except Exception as exc:
            raise RuntimeError("household owner authority unavailable") from exc
        if permitted is not True:
            raise LookupError("draft unavailable")
        with self._connect() as db:
            db.execute("BEGIN")
            rows = db.execute(
                """SELECT * FROM domestic_surplus_draft_revision
                   WHERE household_ref=? ORDER BY offer_ref,revision""",
                (household_ref,),
            ).fetchall()
            db.commit()
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["offer_ref"], []).append(row)
        current = []
        for offer_ref in sorted(grouped):
            chain = grouped[offer_ref]
            self._verify_chain(chain)
            row = chain[-1]
            if row["producer_subject"] != owner:
                raise SurplusDraftIntegrityError(
                    "household draft owner does not match its authorized owner"
                )
            current.append(self._decode(row))
        return tuple(current)

    def history_owned(
        self, principal: Any, household_ref: str, offer_ref: str,
    ) -> tuple[SurplusDraftRevision, ...]:
        """Return an integrity-checked revision history to its household owner."""
        owner = self._authorized_owner(principal, household_ref, offer_ref)
        with self._connect() as db:
            rows = self._chain_rows(db, household_ref, offer_ref)
        if not rows:
            raise LookupError("draft unavailable")
        self._verify_chain(rows)
        if rows[-1]["producer_subject"] != owner:
            raise LookupError("draft unavailable")
        return tuple(self._decode(row) for row in rows)

    def read_owned(
        self, principal: Any, household_ref: str, offer_ref: str,
    ) -> SurplusDraftRevision:
        owner = self._authorized_owner(principal, household_ref, offer_ref)
        with self._connect() as db:
            rows = self._chain_rows(db, household_ref, offer_ref)
        if not rows:
            raise LookupError("draft unavailable")
        self._verify_chain(rows)
        row = rows[-1]
        if row["producer_subject"] != owner:
            raise LookupError("draft unavailable")
        return self._decode(row)

    @staticmethod
    def _decode(row: sqlite3.Row) -> SurplusDraftRevision:
        return SurplusDraftRevision(
            household_ref=row["household_ref"], offer_ref=row["offer_ref"],
            producer_subject=row["producer_subject"], schema_ref=row["schema_ref"],
            schema_version=row["schema_version"], schema_digest=row["schema_digest"],
            revision=row["revision"], values=json.loads(row["values_json"]),
            payload_digest=row["payload_digest"],
            previous_receipt_digest=row["previous_receipt_digest"],
            receipt_digest=row["receipt_digest"],
        )
