"""Audited, revocable record-scope OVERLAY for synthetic D1-A / E0-A tests.

The base ScopedDraft remains immutable. Only a trusted, injected internal
authorizer may revoke an EXISTING synthetic operations grant, with exact
case/grant revision, request identity and append-only local audit. No HTTP
grant mutation, arbitrary assignment, real person or operational datastore.
"""
from dataclasses import dataclass
import hashlib
import json
from threading import RLock
from typing import Callable, Iterable

from .auth import Principal
from .scoped_drafts import (
    ENGINES, ScopedDraft, ScopedSyntheticDraftRegistry,
    _OP_ROLE, _synthetic_ref, _synthetic_subject,
)


class GrantConflict(ValueError):
    """Stale grant revision, replay with changed payload or already revoked."""


class GrantNotAuthorized(ValueError):
    """Missing independent, trusted internal revocation authorization."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditEntry:
    sequence: int
    previous_digest: str
    digest: str
    kind: str
    engine: str
    ref: str
    actor_digest: str
    target_digest: str | None
    case_version: int
    grant_revision: int
    action_id: str | None
    reason_ref: str | None
    access_mode: str | None

    def canonical(self) -> bytes:
        # No mutable payload, raw actor identity, JWT, free text or consent.
        fields = {
            "sequence": self.sequence,
            "previous_digest": self.previous_digest,
            "kind": self.kind,
            "engine": self.engine,
            "ref": self.ref,
            "actor_digest": self.actor_digest,
            "target_digest": self.target_digest,
            "case_version": self.case_version,
            "grant_revision": self.grant_revision,
            "action_id": self.action_id,
            "reason_ref": self.reason_ref,
            "access_mode": self.access_mode,
        }
        return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AuditedSyntheticDraftRegistry(ScopedSyntheticDraftRegistry):
    """Single-instance, lock-serialized synthetic tests. NOT HA/durable audit."""

    def __init__(
        self,
        records: Iterable[ScopedDraft],
        *,
        trusted_revoke_authorizer: Callable[[str, str, str], bool],
        previous_versions: Iterable[ScopedDraft] = (),
    ):
        if not callable(trusted_revoke_authorizer):
            raise ValueError("explicit trusted revocation authorizer is mandatory")
        super().__init__(records)
        self._revoke_authorizer = trusted_revoke_authorizer
        self._lock = RLock()
        self._revoked: set[tuple[str, str, str, str]] = set()
        self._grant_revision = {key: 0 for key in self._catalogue}
        self._replays: dict[str, tuple[tuple, AuditEntry]] = {}
        self._events: list[AuditEntry] = []

        history: dict[tuple[str, str], list[int]] = {
            key: [] for key in self._catalogue
        }
        for record in previous_versions:
            if not isinstance(record, ScopedDraft):
                raise ValueError("only immutable synthetic prior versions are supported")
            key = (record.engine, record.ref)
            current = self._catalogue.get(key)
            if (current is None or record.version >= current.version
                    or record.owner_subject != current.owner_subject):
                raise ValueError("prior version must match the exact current case and owner")
            history[key].append(record.version)
        for key, versions in history.items():
            if len(versions) != len(set(versions)):
                raise ValueError("duplicate prior revision")
            versions.sort()
            versions.append(self._catalogue[key].version)
        # Case revision history is SEED-ONLY, not an operational editing API.
        self._versions = {key: tuple(versions) for key, versions in history.items()}

    def _event(self, *, kind: str, engine: str, ref: str, actor: str,
               target: str | None, action_id: str | None,
               reason_ref: str | None, mode: str | None) -> AuditEntry:
        # Caller MUST hold _lock; digest chain is a local consistency check,
        # NOT a remote signature, durable log or malicious-admin-proof ledger.
        prior = self._events[-1].digest if self._events else "0" * 64
        revision = self._grant_revision[(engine, ref)]
        stub = AuditEntry(
            len(self._events) + 1, prior, "", kind, engine, ref, _digest(actor),
            _digest(target) if target is not None else None,
            self._catalogue[(engine, ref)].version, revision,
            action_id, reason_ref, mode,
        )
        digest = _digest(stub.canonical().decode("utf-8"))
        result = AuditEntry(
            stub.sequence, stub.previous_digest, digest,
            stub.kind, stub.engine, stub.ref, stub.actor_digest,
            stub.target_digest, stub.case_version, stub.grant_revision,
            stub.action_id, stub.reason_ref, stub.access_mode,
        )
        self._events.append(result)
        return result

    def read(self, engine: str, ref: str, principal: Principal,
             *, as_owner: bool) -> dict | None:
        # One serialized access decision and audit event. Revocation cannot
        # race between a successful grant check and that check's audit record.
        with self._lock:
            if (engine not in ENGINES or not _synthetic_ref(ref)
                    or (engine, ref) not in self._catalogue
                    or not isinstance(principal, Principal)
                    or not _synthetic_subject(principal.subject)):
                return None
            response = super().read(engine, ref, principal, as_owner=as_owner)
            if response is not None and not as_owner:
                role = _OP_ROLE[engine]
                if (engine, ref, principal.subject, role) in self._revoked:
                    response = None
            self._event(
                kind="READ_ALLOWED" if response is not None else "READ_DENIED",
                engine=engine, ref=ref, actor=principal.subject, target=None,
                action_id=None, reason_ref=None,
                mode="OWNER" if as_owner else "OPERATIONS",
            )
            return response

    def revoke_grant(
        self, *, engine: str, ref: str, subject: str, role: str,
        actor: str, expected_grant_revision: int,
        action_id: str, reason_ref: str,
    ) -> AuditEntry:
        # This method has NO HTTP route. Caller must inject an independent
        # authorizer; JWT governance or staff roles do NOT automatically pass.
        if (engine not in ENGINES or not _synthetic_ref(ref)
                or not _synthetic_subject(subject) or not _synthetic_subject(actor)
                or role != _OP_ROLE[engine]
                or type(expected_grant_revision) is not int
                or expected_grant_revision < 0
                or not _synthetic_ref(action_id)
                or not _synthetic_ref(reason_ref)):
            raise ValueError("invalid synthetic revocation command")
        with self._lock:
            record = self._catalogue.get((engine, ref))
            if record is None:
                raise GrantConflict("case is not available")
            try:
                permitted = self._revoke_authorizer(actor, engine, ref)
            except Exception as exc:
                raise GrantNotAuthorized("trusted authorizer failed") from exc
            if permitted is not True:
                raise GrantNotAuthorized("separate trusted authorization required")

            command = (engine, ref, subject, role, actor,
                       expected_grant_revision, reason_ref)
            replay = self._replays.get(action_id)
            if replay is not None:
                if replay[0] != command:
                    raise GrantConflict("action replay has changed payload")
                return replay[1]  # exact idempotent replay; no second audit event

            if expected_grant_revision != self._grant_revision[(engine, ref)]:
                raise GrantConflict("stale grant revision")
            identity = (engine, ref, subject, role)
            if (identity in self._revoked
                    or not any(g.subject == subject and g.role == role
                               for g in record.grants)):
                raise GrantConflict("only an active pre-seeded grant can be revoked")
            self._revoked.add(identity)
            self._grant_revision[(engine, ref)] += 1
            try:
                event = self._event(
                    kind="GRANT_REVOKED", engine=engine, ref=ref,
                    actor=actor, target=subject, action_id=action_id,
                    reason_ref=reason_ref, mode=None,
                )
            except Exception:
                # The in-process revocation and journal acceptance form one
                # fail-closed logical step; never leave unaudited mutations.
                self._revoked.remove(identity)
                self._grant_revision[(engine, ref)] -= 1
                raise
            self._replays[action_id] = (command, event)
            return event

    def case_versions(self, engine: str, ref: str) -> tuple[int, ...]:
        with self._lock:
            return self._versions.get((engine, ref), ())

    def grant_revision(self, engine: str, ref: str) -> int | None:
        with self._lock:
            return self._grant_revision.get((engine, ref))

    def audit_snapshot(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._events)

    def verify_local_chain(self) -> bool:
        # Detect accidental local mutation, not privileged deletion/rewrite.
        with self._lock:
            prior = "0" * 64
            for index, entry in enumerate(self._events, start=1):
                if (entry.sequence != index or entry.previous_digest != prior
                        or _digest(entry.canonical().decode("utf-8")) != entry.digest):
                    return False
                prior = entry.digest
            return True
