"""Schema-driven, owner-only synthetic Domestic intake profile.

The active field catalogue is injected by the application; this module does not
invent cultivation fields or scientific thresholds. The SQLite implementation
is LOCAL/TEST and accepts only synthetic household cases.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import sqlite3

from .auth import Principal
from .grant_ledger_sqlite import GENESIS, LedgerIntegrityError, _hash, _json
from .household_input_ledger_sqlite import InputRevisionConflict
from .expert_review_questions_sqlite import SqliteSyntheticExpertQuestionLedger
from .internal_cultivation_plan_contract import _digest
from .scoped_drafts import _synthetic_ref
from .domestic_stage_observation import (
    CurrentStageContext, StageObservationCommand, StageObservationConflict,
    StageObservationReceipt, StageRequirement, receipt_is_current,
    record_stage_observation,
)


_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_SCHEMA_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
PROFILE_EVENT = "SYNTHETIC_HOUSEHOLD_PROFILE_RECORDED"
PROFILE_MODE = "HOUSEHOLD_PROFILE_SHA256:"
STAGE_OBSERVATION_EVENT = "DOMESTIC_STAGE_OBSERVATION_REFERENCE_RECORDED"
STAGE_OBSERVATION_MODE = "DOMESTIC_STAGE_OBSERVATION_RECEIPT:"
STAGE_INSPECTION_EVENT = "DOMESTIC_STAGE_RECEIPT_INSPECTED"
STAGE_INSPECTION_MODE = "DOMESTIC_STAGE_RECEIPT_INSPECTION:"
STAGE_QUESTION_LINK_EVENT = "DOMESTIC_STAGE_FOLLOWUP_QUESTION_LINKED"
STAGE_QUESTION_LINK_MODE = "DOMESTIC_STAGE_FOLLOWUP_QUESTION:"


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


class SqliteSyntheticHouseholdProfileLedger(SqliteSyntheticExpertQuestionLedger):
    """Shared Domestic ledger for profile, specialist questions, and stage receipts."""

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
                CREATE TABLE IF NOT EXISTS household_stage_observation (
                    action_id TEXT PRIMARY KEY, ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL, input_revision INTEGER NOT NULL,
                    input_snapshot_digest TEXT NOT NULL, plan_digest TEXT NOT NULL,
                    stage_ref TEXT NOT NULL, requirements_digest TEXT NOT NULL,
                    observed_at TEXT NOT NULL, artifact_digest TEXT NOT NULL,
                    revision INTEGER NOT NULL, owner_digest TEXT NOT NULL,
                    previous_receipt_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS stage_observation_no_update
                BEFORE UPDATE ON household_stage_observation
                BEGIN SELECT RAISE(ABORT, 'stage observation history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS stage_observation_no_delete
                BEFORE DELETE ON household_stage_observation
                BEGIN SELECT RAISE(ABORT, 'stage observation history immutable'); END;
                CREATE TABLE IF NOT EXISTS expert_stage_receipt_inspection (
                    action_id TEXT PRIMARY KEY, ref TEXT NOT NULL,
                    case_version INTEGER NOT NULL, stage_ref TEXT NOT NULL,
                    observation_revision INTEGER NOT NULL,
                    observation_receipt_digest TEXT NOT NULL,
                    actor_digest TEXT NOT NULL,
                    inspection_receipt TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, stage_ref, observation_revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS stage_receipt_inspection_no_update
                BEFORE UPDATE ON expert_stage_receipt_inspection
                BEGIN SELECT RAISE(ABORT, 'stage receipt inspections immutable'); END;
                CREATE TRIGGER IF NOT EXISTS stage_receipt_inspection_no_delete
                BEFORE DELETE ON expert_stage_receipt_inspection
                BEGIN SELECT RAISE(ABORT, 'stage receipt inspections immutable'); END;
                CREATE TABLE IF NOT EXISTS expert_stage_question_binding (
                    question_action_id TEXT PRIMARY KEY,
                    ref TEXT NOT NULL, case_version INTEGER NOT NULL,
                    track TEXT NOT NULL, question_revision INTEGER NOT NULL,
                    stage_ref TEXT NOT NULL, observation_revision INTEGER NOT NULL,
                    observation_receipt_digest TEXT NOT NULL,
                    actor_digest TEXT NOT NULL,
                    binding_receipt TEXT NOT NULL UNIQUE,
                    audit_sequence INTEGER NOT NULL UNIQUE,
                    UNIQUE(ref, track, question_revision),
                    FOREIGN KEY(audit_sequence) REFERENCES audit_event(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS stage_question_binding_no_update
                BEFORE UPDATE ON expert_stage_question_binding
                BEGIN SELECT RAISE(ABORT, 'stage question bindings immutable'); END;
                CREATE TRIGGER IF NOT EXISTS stage_question_binding_no_delete
                BEFORE DELETE ON expert_stage_question_binding
                BEGIN SELECT RAISE(ABORT, 'stage question bindings immutable'); END;
            """)
        self._profile_ready = True
        with self._transaction() as db:
            self._verify(db)

    def _extended_audit_kinds(self):
        return super()._extended_audit_kinds() | frozenset({
            PROFILE_EVENT, STAGE_OBSERVATION_EVENT, STAGE_INSPECTION_EVENT,
            STAGE_QUESTION_LINK_EVENT,
        })

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
        self._verify_stage_observations(db)

    def _profile_snapshot_from_verified_transaction(
        self, db: sqlite3.Connection, ref: str, version: int,
    ) -> tuple[int, str] | None:
        """Read the schema-current profile from an already verified ledger txn."""
        record = self._catalogue.get(("DOMESTIC", ref))
        if record is None or record.version != version:
            return None
        row = db.execute(
            "SELECT revision,schema_ref,schema_version,schema_digest,"
            "content_digest FROM household_profile_revision "
            "WHERE ref=? ORDER BY revision DESC LIMIT 1", (ref,),
        ).fetchone()
        if row is None:
            return None
        revision, schema_ref, schema_version, schema_digest, content_digest = row
        if (schema_ref != self.profile_schema.schema_ref
                or schema_version != self.profile_schema.version
                or schema_digest != self.profile_schema.digest
                or type(revision) is not int or revision < 1
                or not _digest(content_digest)):
            return None
        return revision, content_digest

    def internal_proposal_lineage(self, ref: str) -> tuple[int, int, str] | None:
        """Return current case/profile version and digest for internal execution.

        This is an internal LOCAL/TEST adapter port. Never expose it through
        household API or BFF responses. Profile values remain inside this ledger.
        """
        if (not isinstance(ref, str) or not _synthetic_ref(ref)
                or not ref.startswith(("DEMO-D", "DEMO-H"))):
            return None
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get(("DOMESTIC", ref))
            snapshot = self._profile_snapshot_from_verified_transaction(
                db, ref, record.version,
            ) if record is not None else None
            if record is None or snapshot is None:
                return None
            return record.version, snapshot[0], snapshot[1]

    def read_owned_profile_revision(
        self, ref: str, principal: Principal, revision: int,
    ) -> dict | None:
        """Owner-only historical values; schema drift hides incompatible content."""
        if type(revision) is not int or revision < 1:
            raise ValueError("invalid household profile revision")
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            row = db.execute(
                "SELECT schema_ref,schema_version,schema_digest,values_json "
                "FROM household_profile_revision WHERE ref=? AND revision=?",
                (ref, revision),
            ).fetchone()
            if row is None:
                return None
            matches_schema = row[:3] == (
                self.profile_schema.schema_ref, self.profile_schema.version,
                self.profile_schema.digest,
            )
            self._append(
                db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                actor=principal.subject,
                mode="HOUSEHOLD_PROFILE_REVISION:" + str(revision),
            )
            return {
                "engine": "DOMESTIC", "ref": ref,
                "case_version": record.version, "revision": revision,
                "values": json.loads(row[3]) if matches_schema else {},
                "schema_changed": not matches_schema,
                "purpose_consent_verified": False,
                "science_validated": False, "plan_accepted": False,
            }

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

    @staticmethod
    def _stage_receipt_view(receipt: StageObservationReceipt) -> dict:
        return {
            "contract_version": receipt.contract_version,
            "case_ref": receipt.case_ref,
            "case_version": receipt.case_version,
            "input_revision": receipt.input_revision,
            "stage_ref": receipt.stage_ref,
            "observed_at": receipt.observed_at,
            "observation_artifact_digest": receipt.observation_artifact_digest,
            "revision": receipt.revision,
            "previous_receipt_digest": receipt.previous_receipt_digest,
            "receipt_digest": receipt.receipt_digest,
            "status": receipt.status,
            "stage_completed": False,
            "scientific_review_approved": False,
            "advice_enabled": False,
            "real_data": False,
        }

    def _verify_stage_observations(self, db: sqlite3.Connection) -> None:
        linked = {}
        for sequence, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            if (event.get("kind") == STAGE_OBSERVATION_EVENT
                    or isinstance(mode, str)
                       and mode.startswith(STAGE_OBSERVATION_MODE)):
                linked[sequence] = event
        used, prior_by_ref, revision_by_ref = set(), {}, {}
        rows = db.execute(
            "SELECT action_id,ref,case_version,input_revision,input_snapshot_digest,"
            "plan_digest,stage_ref,requirements_digest,observed_at,artifact_digest,"
            "revision,owner_digest,previous_receipt_digest,receipt_digest,audit_sequence "
            "FROM household_stage_observation ORDER BY audit_sequence"
        )
        for row in rows:
            (action, ref, case_version, input_revision, input_digest, plan_digest,
             stage_ref, requirements_digest, observed_at, artifact_digest,
             revision, owner_digest, previous, receipt, sequence) = row
            record = self._catalogue.get(("DOMESTIC", ref))
            expected_previous = prior_by_ref.get(ref, GENESIS)
            expected_revision = revision_by_ref.get(ref, 0) + 1
            event = linked.get(sequence)
            try:
                command = StageObservationCommand(
                    action_id=action, expected_case_version=case_version,
                    expected_input_revision=input_revision,
                    expected_input_snapshot_digest=input_digest,
                    expected_plan_digest=plan_digest, stage_ref=stage_ref,
                    expected_observation_requirements_digest=requirements_digest,
                    observed_at=observed_at,
                    observation_artifact_digest=artifact_digest,
                )
                current = CurrentStageContext(
                    case_ref=ref, case_version=case_version,
                    input_revision=input_revision,
                    input_snapshot_digest=input_digest, plan_digest=plan_digest,
                    requirements=(StageRequirement(stage_ref, requirements_digest),),
                )
                expected = record_stage_observation(
                    command, current=current, revision=revision,
                    previous_receipt_digest=previous,
                )
            except (TypeError, ValueError) as exc:
                raise LedgerIntegrityError(
                    "invalid Domestic stage observation receipt"
                ) from exc
            if (record is None or case_version != record.version
                    or not _synthetic_ref(action)
                    or type(input_revision) is not int or input_revision < 1
                    or not _digest(input_digest) or not _digest(plan_digest)
                    or type(revision) is not int or revision != expected_revision
                    or owner_digest != _hash(record.owner_subject)
                    or previous != expected_previous
                    or receipt != expected.receipt_digest
                    or event is None
                    or event.get("kind") != STAGE_OBSERVATION_EVENT
                    or event.get("engine") != "DOMESTIC"
                    or event.get("ref") != ref
                    or event.get("case_version") != case_version
                    or event.get("action_id") != action
                    or event.get("actor_digest") != owner_digest
                    or event.get("target_digest") != _hash(receipt)
                    or event.get("access_mode") != STAGE_OBSERVATION_MODE + receipt):
                raise LedgerIntegrityError(
                    "Domestic stage observation/audit mismatch"
                )
            if sequence in used:
                raise LedgerIntegrityError("duplicate stage observation audit")
            used.add(sequence)
            prior_by_ref[ref] = receipt
            revision_by_ref[ref] = revision
        if used != set(linked):
            raise LedgerIntegrityError("orphaned Domestic stage observation audit")
        self._verify_stage_receipt_inspections(db)
        self._verify_stage_question_bindings(db)

    @staticmethod
    def _stage_question_binding(
        action: str, ref: str, case_version: int, track: str,
        question_revision: int, stage_ref: str, observation_revision: int,
        observation_receipt_digest: str, actor_digest: str,
    ) -> dict:
        return {
            "question_action_id": action, "engine": "DOMESTIC", "ref": ref,
            "case_version": case_version, "track": track,
            "question_revision": question_revision, "stage_ref": stage_ref,
            "observation_revision": observation_revision,
            "observation_receipt_digest": observation_receipt_digest,
            "actor_digest": actor_digest,
        }

    def _verify_stage_question_bindings(
        self, db: sqlite3.Connection,
    ) -> None:
        linked = {}
        for sequence, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            structural_mismatch = (
                not _synthetic_ref(action) or not _synthetic_ref(ref)
                or not _synthetic_ref(stage_ref)
                or type(case_version) is not int or case_version < 1
                or track != "HOUSEHOLD_INPUT_ADEQUACY"
                or type(question_revision) is not int or question_revision < 1
                or type(observation_revision) is not int or observation_revision < 1
                or not _digest(observation_digest)
            )
            if structural_mismatch:
                raise LedgerIntegrityError(
                    "stage follow-up question structural binding mismatch"
                )
            if observation != (case_version, observation_digest):
                raise LedgerIntegrityError(
                    "stage follow-up question receipt mismatch"
                )
            if (question is None
                    or question[:5] != (
                        ref, track, question_revision, case_version, actor_digest,
                    )
                    or question[5] >= sequence):
                raise LedgerIntegrityError(
                    "stage follow-up question record mismatch"
                )
            if receipt != expected_receipt:
                raise LedgerIntegrityError(
                    "stage follow-up question binding digest mismatch"
                )
            if (event is None
                    or event.get("kind") != STAGE_QUESTION_LINK_EVENT
                    or event.get("engine") != "DOMESTIC"
                    or event.get("ref") != ref
                    or event.get("case_version") != case_version
                    or event.get("action_id") != action
                    or event.get("actor_digest") != actor_digest
                    or event.get("reason_ref") != stage_ref
                    or event.get("target_digest") != _hash(receipt)
                    or event.get("access_mode") != STAGE_QUESTION_LINK_MODE + receipt
                    or sequence in used):
                raise LedgerIntegrityError(
                    "stage follow-up question audit mismatch"
                )
            used.add(sequence)
        if used != set(linked):
            raise LedgerIntegrityError("orphaned stage follow-up question binding audit")

    def _append_verified_stage_question_binding(
        self, db: sqlite3.Connection, *, question_action_id: str,
        ref: str, case_version: int, track: str, question_revision: int,
        stage_ref: str, observation_revision: int,
        observation_receipt_digest: str, actor: str,
    ) -> None:
        actor_digest = _hash(actor)
        binding = self._stage_question_binding(
            question_action_id, ref, case_version, track, question_revision,
            stage_ref, observation_revision, observation_receipt_digest,
            actor_digest,
        )
        receipt = _hash(_json(binding))
        prior = db.execute(
            "SELECT ref,case_version,track,question_revision,stage_ref,"
            "observation_revision,observation_receipt_digest,actor_digest,"
            "binding_receipt FROM expert_stage_question_binding "
            "WHERE question_action_id=?", (question_action_id,),
        ).fetchone()
        expected = (
            ref, case_version, track, question_revision, stage_ref,
            observation_revision, observation_receipt_digest, actor_digest, receipt,
        )
        if prior is not None:
            if prior == expected:
                return
            raise StageObservationConflict("stage question replay differs")
        if db.execute(
            "SELECT 1 FROM expert_stage_question_binding "
            "WHERE ref=? AND track=? AND question_revision=?",
            (ref, track, question_revision),
        ).fetchone() is not None:
            raise StageObservationConflict("question already linked to a stage")
        audit = self._append(
            db, kind=STAGE_QUESTION_LINK_EVENT, engine="DOMESTIC",
            ref=ref, actor=actor, target=receipt,
            action_id=question_action_id, reason_ref=stage_ref,
            mode=STAGE_QUESTION_LINK_MODE + receipt,
        )
        db.execute(
            "INSERT INTO expert_stage_question_binding "
            "(question_action_id,ref,case_version,track,question_revision,"
            "stage_ref,observation_revision,observation_receipt_digest,"
            "actor_digest,binding_receipt,audit_sequence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (question_action_id, ref, case_version, track, question_revision,
             stage_ref, observation_revision, observation_receipt_digest,
             actor_digest, receipt, audit.sequence),
        )

    @staticmethod
    def _stage_inspection_binding(
        action: str, ref: str, case_version: int, stage_ref: str,
        observation_revision: int, observation_receipt_digest: str,
        actor_digest: str,
    ) -> dict:
        return {
            "action_id": action, "engine": "DOMESTIC", "ref": ref,
            "case_version": case_version, "stage_ref": stage_ref,
            "observation_revision": observation_revision,
            "observation_receipt_digest": observation_receipt_digest,
            "actor_digest": actor_digest,
        }

    def _verify_stage_receipt_inspections(
        self, db: sqlite3.Connection,
    ) -> None:
        linked = {}
        for sequence, payload in db.execute(
            "SELECT sequence,payload FROM audit_event ORDER BY sequence"
        ):
            event = json.loads(payload)
            mode = event.get("access_mode")
            if (event.get("kind") == STAGE_INSPECTION_EVENT
                    or isinstance(mode, str)
                       and mode.startswith(STAGE_INSPECTION_MODE)):
                linked[sequence] = event
        used = set()
        rows = db.execute(
            "SELECT action_id,ref,case_version,stage_ref,observation_revision,"
            "observation_receipt_digest,actor_digest,inspection_receipt,audit_sequence "
            "FROM expert_stage_receipt_inspection ORDER BY audit_sequence"
        )
        for row in rows:
            (action, ref, case_version, stage_ref, observation_revision,
             observation_digest, actor_digest, receipt, sequence) = row
            record = self._catalogue.get(("DOMESTIC", ref))
            observed = db.execute(
                "SELECT case_version,receipt_digest FROM household_stage_observation "
                "WHERE ref=? AND stage_ref=? AND revision=?",
                (ref, stage_ref, observation_revision),
            ).fetchone()
            event = linked.get(sequence)
            binding = self._stage_inspection_binding(
                action, ref, case_version, stage_ref, observation_revision,
                observation_digest, actor_digest,
            )
            expected_receipt = _hash(_json(binding))
            if (record is None or case_version != record.version
                    or not _synthetic_ref(action) or not _synthetic_ref(stage_ref)
                    or type(observation_revision) is not int
                    or observation_revision < 1 or observed is None
                    or observed != (case_version, observation_digest)
                    or not _digest(actor_digest) or actor_digest == _hash(record.owner_subject)
                    or receipt != expected_receipt or event is None
                    or event.get("kind") != STAGE_INSPECTION_EVENT
                    or event.get("engine") != "DOMESTIC"
                    or event.get("ref") != ref
                    or event.get("case_version") != case_version
                    or event.get("action_id") != action
                    or event.get("actor_digest") != actor_digest
                    or event.get("reason_ref") != stage_ref
                    or event.get("target_digest") != _hash(receipt)
                    or event.get("access_mode") != STAGE_INSPECTION_MODE + receipt
                    or sequence in used):
                raise LedgerIntegrityError(
                    "stage receipt inspection/audit mismatch"
                )
            used.add(sequence)
        if used != set(linked):
            raise LedgerIntegrityError("orphaned stage receipt inspection audit")

    def _append_verified_stage_receipt_inspection(
        self, db: sqlite3.Connection, *, ref: str, case_version: int,
        stage_ref: str, observation_revision: int,
        observation_receipt_digest: str, actor: str, action_id: str,
    ) -> dict:
        if (not all(_synthetic_ref(value) for value in (ref, stage_ref, action_id))
                or type(case_version) is not int or case_version < 1
                or type(observation_revision) is not int
                or observation_revision < 1
                or not _digest(observation_receipt_digest)):
            raise ValueError("invalid stage receipt inspection")
        record = self._catalogue.get(("DOMESTIC", ref))
        observed = db.execute(
            "SELECT case_version,receipt_digest FROM household_stage_observation "
            "WHERE ref=? AND stage_ref=? AND revision=?",
            (ref, stage_ref, observation_revision),
        ).fetchone()
        actor_digest = _hash(actor)
        if (record is None or record.version != case_version
                or observed != (case_version, observation_receipt_digest)
                or actor_digest == _hash(record.owner_subject)):
            raise StageObservationConflict("stage receipt or reviewer context changed")
        binding = self._stage_inspection_binding(
            action_id, ref, case_version, stage_ref, observation_revision,
            observation_receipt_digest, actor_digest,
        )
        receipt = _hash(_json(binding))
        prior_action = db.execute(
            "SELECT ref,case_version,stage_ref,observation_revision,"
            "observation_receipt_digest,actor_digest,inspection_receipt "
            "FROM expert_stage_receipt_inspection WHERE action_id=?",
            (action_id,),
        ).fetchone()
        expected = (
            ref, case_version, stage_ref, observation_revision,
            observation_receipt_digest, actor_digest, receipt,
        )
        if prior_action is not None:
            if prior_action == expected:
                return self._stage_inspection_ack(
                    ref, stage_ref, observation_revision, True,
                )
            raise StageObservationConflict("stage inspection action replay differs")
        prior_receipt = db.execute(
            "SELECT action_id,inspection_receipt "
            "FROM expert_stage_receipt_inspection "
            "WHERE ref=? AND stage_ref=? AND observation_revision=?",
            (ref, stage_ref, observation_revision),
        ).fetchone()
        if prior_receipt is not None:
            if prior_receipt == (action_id, receipt):
                return self._stage_inspection_ack(
                    ref, stage_ref, observation_revision, True,
                )
            raise StageObservationConflict("stage receipt was already inspected")
        audit = self._append(
            db, kind=STAGE_INSPECTION_EVENT, engine="DOMESTIC", ref=ref,
            actor=actor, target=receipt, action_id=action_id,
            reason_ref=stage_ref, mode=STAGE_INSPECTION_MODE + receipt,
        )
        db.execute(
            "INSERT INTO expert_stage_receipt_inspection "
            "(action_id,ref,case_version,stage_ref,observation_revision,"
            "observation_receipt_digest,actor_digest,inspection_receipt,audit_sequence) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (action_id, ref, case_version, stage_ref, observation_revision,
             observation_receipt_digest, actor_digest, receipt, audit.sequence),
        )
        return self._stage_inspection_ack(
            ref, stage_ref, observation_revision, False,
        )

    @staticmethod
    def _stage_inspection_ack(
        ref: str, stage_ref: str, observation_revision: int, replay: bool,
    ) -> dict:
        return {
            "engine": "DOMESTIC", "case_ref": ref, "stage_ref": stage_ref,
            "observation_revision": observation_revision,
            "record_state": "SYNTHETIC_STAGE_RECEIPT_INSPECTED_NOT_REVIEWED",
            "idempotent_replay": replay, "review_completed": False,
            "stage_completed": False, "scientific_approval": False,
            "real_data": False,
        }

    @staticmethod
    def _read_stage_context(
        ref: str,
        context_authority: Callable[[str], CurrentStageContext | None],
    ) -> CurrentStageContext | None:
        if not callable(context_authority):
            raise ValueError("current stage context authority required")
        try:
            context = context_authority(ref)
        except Exception as exc:
            raise LedgerIntegrityError(
                "current stage context authority unavailable"
            ) from exc
        if context is not None and (
                not isinstance(context, CurrentStageContext)
                or context.case_ref != ref):
            raise LedgerIntegrityError("untrusted current stage context")
        return context

    def _resolve_stage_context(
        self, db: sqlite3.Connection, ref: str,
        context: CurrentStageContext | None,
    ) -> CurrentStageContext | None:
        record = self._catalogue.get(("DOMESTIC", ref))
        if record is None or context is None:
            return None
        snapshot = self._profile_snapshot_from_verified_transaction(
            db, ref, record.version,
        )
        if (context.case_version != record.version or snapshot is None
                or context.input_revision != snapshot[0]
                or context.input_snapshot_digest != snapshot[1]):
            raise StageObservationConflict("current household input changed")
        return context

    def _stage_observation_read_view(self, db, ref, record, context) -> dict:
        rows = db.execute(
            "SELECT action_id,case_version,input_revision,input_snapshot_digest,"
            "plan_digest,stage_ref,requirements_digest,observed_at,artifact_digest,"
            "revision,previous_receipt_digest,receipt_digest "
            "FROM household_stage_observation WHERE ref=? ORDER BY revision",
            (ref,),
        ).fetchall()
        inspected = {
            (stage_ref, revision)
            for stage_ref, revision in db.execute(
                "SELECT stage_ref,observation_revision "
                "FROM expert_stage_receipt_inspection WHERE ref=?", (ref,),
            )
        }
        items = []
        for row in rows:
            (action, version, input_revision, input_digest, plan_digest,
             stage_ref, requirements_digest, observed_at, artifact_digest,
             revision, previous, digest) = row
            receipt = StageObservationReceipt(
                contract_version="ronas.domestic.stage-observation-receipt.v0",
                case_ref=ref, case_version=version,
                input_revision=input_revision,
                input_snapshot_digest=input_digest, plan_digest=plan_digest,
                stage_ref=stage_ref,
                observation_requirements_digest=requirements_digest,
                observed_at=observed_at,
                observation_artifact_digest=artifact_digest,
                revision=revision, previous_receipt_digest=previous,
                receipt_digest=digest,
            )
            items.append({
                "revision": revision, "stage_ref": stage_ref,
                "observed_at": observed_at,
                "observation_artifact_digest": artifact_digest,
                "receipt_digest": digest,
                "receipt_inspected": (stage_ref, revision) in inspected,
                "inspection_is_review": False,
                "current": bool(context and receipt_is_current(receipt, context)),
                "status": "OBSERVATION_REFERENCE_RECORDED",
                "stage_completed": False,
            })
        latest_by_stage = {}
        for observation in items:
            latest_by_stage[observation["stage_ref"]] = observation
        stage_progress = []
        if context is not None:
            for requirement in context.requirements:
                latest = latest_by_stage.get(requirement.stage_ref)
                stage_progress.append({
                    "stage_ref": requirement.stage_ref,
                    "state": (
                        "NOT_REPORTED" if latest is None else
                        "CURRENT_RECEIPT" if latest["current"] else
                        "HISTORICAL_RECEIPT"
                    ),
                    "observation_revision": (
                        latest["revision"] if latest is not None else None
                    ),
                    "receipt_inspected": bool(
                        latest is not None and latest["receipt_inspected"]
                    ),
                })
        return {
            "engine": "DOMESTIC", "ref": ref,
            "case_version": record.version,
            "state": "CURRENT_PLAN_AVAILABLE" if context else "NO_CURRENT_PLAN",
            "current_context": ({
                "case_version": context.case_version,
                "input_revision": context.input_revision,
                "input_snapshot_digest": context.input_snapshot_digest,
                "plan_digest": context.plan_digest,
                "stages": [{
                    "stage_ref": item.stage_ref,
                    "observation_requirements_digest":
                        item.observation_requirements_digest,
                } for item in context.requirements],
            } if context else None),
            "current_revision": rows[-1][9] if rows else 0,
            "observations": items,
            "stage_progress": stage_progress,
            "real_data": False,
            "scientific_review_approved": False,
            "plan_accepted": False,
        }

    def read_owned_stage_observations(
        self, ref: str, principal: Principal, *,
        context_authority: Callable[[str], CurrentStageContext | None],
    ) -> dict | None:
        if not self._owner(ref, principal):
            return None
        provided_context = self._read_stage_context(ref, context_authority)
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            context = self._resolve_stage_context(db, ref, provided_context)
            result = self._stage_observation_read_view(db, ref, record, context)
            self._append(
                db, kind="READ_ALLOWED", engine="DOMESTIC", ref=ref,
                actor=principal.subject, mode="HOUSEHOLD_STAGE_OBSERVATIONS",
            )
            return result

    def append_owned_stage_observation(
        self, ref: str, principal: Principal, command: StageObservationCommand, *,
        expected_observation_revision: int,
        context_authority: Callable[[str], CurrentStageContext | None],
    ) -> dict | None:
        if (not isinstance(command, StageObservationCommand)
                or type(expected_observation_revision) is not int
                or expected_observation_revision < 0):
            raise ValueError("invalid stage observation command")
        if not self._owner(ref, principal):
            return None
        provided_context = self._read_stage_context(ref, context_authority)
        with self._transaction() as db:
            self._verify(db)
            if not self._owner(ref, principal):
                return None
            record = self._catalogue[("DOMESTIC", ref)]
            if record.version != command.expected_case_version:
                raise StageObservationConflict("household case changed")
            context = self._resolve_stage_context(db, ref, provided_context)
            if context is None:
                raise StageObservationConflict("no current plan is available")
            existing = db.execute(
                "SELECT ref,case_version,input_revision,input_snapshot_digest,"
                "plan_digest,stage_ref,requirements_digest,observed_at,artifact_digest,"
                "revision,owner_digest,previous_receipt_digest,receipt_digest "
                "FROM household_stage_observation WHERE action_id=?",
                (command.action_id,),
            ).fetchone()
            actor = _hash(principal.subject)
            expected_existing = (
                ref, command.expected_case_version, command.expected_input_revision,
                command.expected_input_snapshot_digest, command.expected_plan_digest,
                command.stage_ref, command.expected_observation_requirements_digest,
                command.observed_at, command.observation_artifact_digest,
            )
            if existing is not None:
                if existing[:9] == expected_existing and existing[10] == actor:
                    return {
                        "ref": ref, "revision": existing[9],
                        "receipt_digest": existing[12], "idempotent_replay": True,
                        "stage_completed": False,
                    }
                raise StageObservationConflict("conflicting action replay")
            previous_row = db.execute(
                "SELECT revision,receipt_digest FROM household_stage_observation "
                "WHERE ref=? ORDER BY revision DESC LIMIT 1", (ref,),
            ).fetchone()
            current_revision = previous_row[0] if previous_row else 0
            if current_revision != expected_observation_revision:
                raise StageObservationConflict("observation history changed")
            previous = previous_row[1] if previous_row else GENESIS
            receipt = record_stage_observation(
                command, current=context, revision=current_revision + 1,
                previous_receipt_digest=previous,
            )
            audit = self._append(
                db, kind=STAGE_OBSERVATION_EVENT, engine="DOMESTIC",
                ref=ref, actor=principal.subject, target=receipt.receipt_digest,
                action_id=command.action_id,
                mode=STAGE_OBSERVATION_MODE + receipt.receipt_digest,
            )
            db.execute(
                "INSERT INTO household_stage_observation "
                "(action_id,ref,case_version,input_revision,input_snapshot_digest,"
                "plan_digest,stage_ref,requirements_digest,observed_at,artifact_digest,"
                "revision,owner_digest,previous_receipt_digest,receipt_digest,audit_sequence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (command.action_id, ref, receipt.case_version, receipt.input_revision,
                 receipt.input_snapshot_digest, receipt.plan_digest, receipt.stage_ref,
                 receipt.observation_requirements_digest, receipt.observed_at,
                 receipt.observation_artifact_digest, receipt.revision, actor,
                 receipt.previous_receipt_digest, receipt.receipt_digest,
                 audit.sequence),
            )
            return {
                "ref": ref, "revision": receipt.revision,
                "receipt_digest": receipt.receipt_digest,
                "idempotent_replay": False, "stage_completed": False,
                "status": receipt.status,
            }

