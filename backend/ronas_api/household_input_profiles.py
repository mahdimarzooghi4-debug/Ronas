"""Schema-driven, owner-only synthetic Domestic intake profile.

The active field catalogue is injected by the application; this module does not
invent cultivation fields or scientific thresholds. The SQLite implementation
is LOCAL/TEST and accepts only synthetic household cases.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import sqlite3

from .auth import Principal
from .grant_ledger_sqlite import GENESIS, LedgerIntegrityError, _hash, _json
from .household_input_ledger_sqlite import (
    InputRevisionConflict, SqliteSyntheticHouseholdInputLedger,
)
from .internal_cultivation_plan_contract import _digest
from .scoped_drafts import _synthetic_ref


_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_SCHEMA_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
PROFILE_EVENT = "SYNTHETIC_HOUSEHOLD_PROFILE_RECORDED"
PROFILE_MODE = "HOUSEHOLD_PROFILE_SHA256:"


@dataclass(frozen=True, slots=True)
class HouseholdInputField:
    key: str
    label: str
    kind: str = "text"
    required: bool = False
    max_length: int = 120
    choices: tuple[str, ...] = ()

    def __post_init__(self):
        if (not isinstance(self.key, str) or not _KEY.fullmatch(self.key)
                or not isinstance(self.label, str) or not self.label.strip()
                or len(self.label) > 100
                or self.kind not in ("text", "number", "date", "choice")
                or type(self.required) is not bool
                or type(self.max_length) is not int
                or not 1 <= self.max_length <= 300
                or type(self.choices) is not tuple
                or len(self.choices) > 30
                or any(not isinstance(x, str) or not x or len(x) > 80
                       for x in self.choices)
                or len(set(self.choices)) != len(self.choices)
                or self.kind == "choice" and not self.choices
                or self.kind != "choice" and self.choices):
            raise ValueError("invalid household input field definition")


@dataclass(frozen=True, slots=True)
class HouseholdInputSchema:
    schema_ref: str
    version: int
    fields: tuple[HouseholdInputField, ...]

    def __post_init__(self):
        if (not isinstance(self.schema_ref, str)
                or not _SCHEMA_REF.fullmatch(self.schema_ref)
                or type(self.version) is not int or self.version < 1
                or type(self.fields) is not tuple
                or not 1 <= len(self.fields) <= 6
                or any(not isinstance(x, HouseholdInputField) for x in self.fields)
                or len({x.key for x in self.fields}) != len(self.fields)):
            raise ValueError("invalid household input schema")

    @property
    def digest(self) -> str:
        body = {
            "schema_ref": self.schema_ref, "version": self.version,
            "fields": [{
                "key": x.key, "label": x.label, "kind": x.kind,
                "required": x.required, "max_length": x.max_length,
                "choices": list(x.choices),
            } for x in self.fields],
        }
        return hashlib.sha256(_json(body).encode("utf-8")).hexdigest()

    def validate(self, values: dict[str, str]) -> dict[str, str]:
        if not isinstance(values, dict) or set(values) - {x.key for x in self.fields}:
            raise ValueError("household profile has unknown fields")
        result = {}
        for item in self.fields:
            value = values.get(item.key, "")
            if not isinstance(value, str):
                raise ValueError("household profile values must be strings")
            if len(value) > item.max_length:
                raise ValueError("household profile value too long")
            if item.required and not value.strip():
                raise ValueError("required household profile value missing")
            if value and item.kind == "choice" and value not in item.choices:
                raise ValueError("household profile choice is not allowed")
            if value and item.kind == "number":
                try:
                    parsed = Decimal(value)
                except InvalidOperation as exc:
                    raise ValueError("household profile number is invalid") from exc
                if not parsed.is_finite():
                    raise ValueError("household profile number is invalid")
            if value and item.kind == "date":
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError("household profile date is invalid") from exc
            result[item.key] = value
        return result


class SqliteSyntheticHouseholdProfileLedger(SqliteSyntheticHouseholdInputLedger):
    """Profile revisions share the same owner, audit chain and case database."""

    def __init__(self, *args, profile_schema: HouseholdInputSchema, **kwargs):
        if not isinstance(profile_schema, HouseholdInputSchema):
            raise ValueError("explicit household input schema required")
        self.profile_schema = profile_schema
        self._profile_ready = False
        super().__init__(*args, **kwargs)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS household_profile_revision (
                    action_id TEXT PRIMARY KEY, ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL, revision INTEGER NOT NULL,
                    owner_digest TEXT NOT NULL, schema_ref TEXT NOT NULL,
                    schema_version INTEGER NOT NULL, schema_digest TEXT NOT NULL,
                    values_json TEXT NOT NULL, content_digest TEXT NOT NULL,
                    previous_receipt_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS household_profile_no_update
                BEFORE UPDATE ON household_profile_revision
                BEGIN SELECT RAISE(ABORT, 'household profile history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS household_profile_no_delete
                BEFORE DELETE ON household_profile_revision
                BEGIN SELECT RAISE(ABORT, 'household profile history immutable'); END;
            """)
        self._profile_ready = True
        with self._transaction() as db:
            self._verify(db)

    def _extended_audit_kinds(self):
        return super()._extended_audit_kinds() | frozenset({PROFILE_EVENT})

    @staticmethod
    def _content_digest(schema_digest: str, values_json: str) -> str:
        return hashlib.sha256(_json({
            "schema_digest": schema_digest, "values_json": values_json,
        }).encode("utf-8")).hexdigest()

    @staticmethod
    def _profile_receipt(action, ref, case_version, revision, owner_digest,
                         schema_ref, schema_version, schema_digest,
                         content_digest, previous):
        return _hash(_json({
            "action_id": action, "engine": "DOMESTIC", "ref": ref,
            "case_version": case_version, "revision": revision,
            "owner_digest": owner_digest, "schema_ref": schema_ref,
            "schema_version": schema_version, "schema_digest": schema_digest,
            "content_digest": content_digest, "previous_receipt_digest": previous,
        }))

    def _verify(self, db: sqlite3.Connection) -> None:
        super()._verify(db)
        if not getattr(self, "_profile_ready", False):
            return
        linked = {}
        for sequence, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            if (event.get("kind") == PROFILE_EVENT
                    or isinstance(mode, str) and mode.startswith(PROFILE_MODE)):
                linked[sequence] = event
        used, prior_by_ref, revision_by_ref = set(), {}, {}
        for row in db.execute(
            "SELECT action_id,ref,case_version,revision,owner_digest,schema_ref,"
            "schema_version,schema_digest,values_json,content_digest,"
            "previous_receipt_digest,receipt_digest,audit_sequence "
            "FROM household_profile_revision ORDER BY audit_sequence"
        ):
            (action, ref, version, revision, actor, schema_ref, schema_version,
             schema_digest, values_json, content_digest, previous, receipt,
             sequence) = row
            record = self._catalogue.get(("DOMESTIC", ref))
            expected_revision = revision_by_ref.get(ref, 0) + 1
            expected_previous = prior_by_ref.get(ref, GENESIS)
            event = linked.get(sequence)
            try:
                values = json.loads(values_json)
                canonical = _json(values)
                value_valid = (canonical == values_json and isinstance(values, dict)
                               and all(isinstance(k, str) and isinstance(v, str)
                                       for k, v in values.items()))
            except (TypeError, ValueError):
                value_valid = False
            expected_content = self._content_digest(schema_digest, values_json)
            expected_receipt = self._profile_receipt(
                action, ref, version, revision, actor, schema_ref, schema_version,
                schema_digest, content_digest, previous,
            )
            if (record is None or not _synthetic_ref(action)
                    or version != record.version or type(revision) is not int
                    or revision != expected_revision or actor != _hash(record.owner_subject)
                    or not isinstance(schema_ref, str) or not isinstance(schema_ref, str) or not _SCHEMA_REF.fullmatch(schema_ref)
                    or type(schema_version) is not int or schema_version < 1
                    or not _digest(schema_digest) or not value_valid
                    or content_digest != expected_content or previous != expected_previous
                    or receipt != expected_receipt or event is None
                    or event.get("kind") != PROFILE_EVENT
                    or event.get("engine") != "DOMESTIC" or event.get("ref") != ref
                    or event.get("case_version") != version
                    or event.get("action_id") != action
                    or event.get("actor_digest") != actor
                    or event.get("target_digest") != _hash(receipt)
                    or event.get("access_mode") != PROFILE_MODE + receipt):
                raise LedgerIntegrityError("household profile/audit mismatch")
            if sequence in used:
                raise LedgerIntegrityError("duplicate household profile audit")
            used.add(sequence); prior_by_ref[ref] = receipt; revision_by_ref[ref] = revision
        if used != set(linked):
            raise LedgerIntegrityError("orphaned household profile audit")

    def read_owned_profile(self, ref: str, principal: Principal) -> dict | None:
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            rows = db.execute(
                "SELECT revision,schema_ref,schema_version,schema_digest,values_json,"
                "content_digest,receipt_digest FROM household_profile_revision "
                "WHERE ref=? ORDER BY revision", (ref,),
            ).fetchall()
            self._append(db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                         actor=principal.subject, mode="HOUSEHOLD_PROFILE_HISTORY")
            current = rows[-1] if rows else None
            matches_schema = bool(current and current[1:4] == (
                self.profile_schema.schema_ref, self.profile_schema.version,
                self.profile_schema.digest,
            ))
            return {
                "engine": "DOMESTIC", "ref": ref, "case_version": record.version,
                "schema_ref": self.profile_schema.schema_ref,
                "schema_version": self.profile_schema.version,
                "schema_digest": self.profile_schema.digest,
                "revisions": [{
                    "revision": row[0], "schema_ref": row[1],
                    "schema_version": row[2],
                } for row in rows],
                "current_revision": current[0] if current else 0,
                "current_values": json.loads(current[4]) if matches_schema else {},
                "schema_changed": bool(current and not matches_schema),
                "purpose_consent_verified": False,
                "science_validated": False, "plan_accepted": False,
            }

    def append_owned_profile(
        self, ref: str, principal: Principal, *, action_id: str,
        expected_case_version: int, expected_revision: int,
        values: dict[str, str],
    ) -> dict | None:
        if (not _synthetic_ref(action_id)
                or type(expected_case_version) is not int or expected_case_version < 1
                or type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("invalid household profile command")
        normalized = self.profile_schema.validate(values)
        values_json = _json(normalized)
        schema = self.profile_schema
        content = self._content_digest(schema.digest, values_json)
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            if record.version != expected_case_version:
                raise InputRevisionConflict("stale household case")
            actor = _hash(principal.subject)
            prior_action = db.execute(
                "SELECT ref,case_version,revision,owner_digest,schema_ref,schema_version,"
                "schema_digest,values_json,content_digest FROM household_profile_revision "
                "WHERE action_id=?", (action_id,),
            ).fetchone()
            expected_row = (ref, expected_case_version, expected_revision + 1, actor,
                            schema.schema_ref, schema.version, schema.digest,
                            values_json, content)
            if prior_action is not None:
                if prior_action == expected_row:
                    return {"ref": ref, "case_version": record.version,
                            "profile_revision": expected_revision + 1,
                            "idempotent_replay": True}
                raise InputRevisionConflict("conflicting household profile replay")
            previous_row = db.execute(
                "SELECT revision,content_digest,receipt_digest FROM household_profile_revision "
                "WHERE ref=? ORDER BY revision DESC LIMIT 1", (ref,),
            ).fetchone()
            current_revision = previous_row[0] if previous_row else 0
            if current_revision != expected_revision:
                raise InputRevisionConflict("stale household profile revision")
            if previous_row and previous_row[1] == content:
                raise InputRevisionConflict("unchanged household profile")
            previous = previous_row[2] if previous_row else GENESIS
            revision = current_revision + 1
            receipt = self._profile_receipt(
                action_id, ref, record.version, revision, actor, schema.schema_ref,
                schema.version, schema.digest, content, previous,
            )
            audit = self._append(
                db, kind=PROFILE_EVENT, engine="DOMESTIC", ref=ref,
                actor=principal.subject, target=receipt, action_id=action_id,
                mode=PROFILE_MODE + receipt,
            )
            db.execute(
                "INSERT INTO household_profile_revision "
                "(action_id,ref,case_version,revision,owner_digest,schema_ref,"
                "schema_version,schema_digest,values_json,content_digest,"
                "previous_receipt_digest,receipt_digest,audit_sequence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (action_id, ref, record.version, revision, actor, schema.schema_ref,
                 schema.version, schema.digest, values_json, content, previous,
                 receipt, audit.sequence),
            )
            return {"ref": ref, "case_version": record.version,
                    "profile_revision": revision,
                    "idempotent_replay": False}
