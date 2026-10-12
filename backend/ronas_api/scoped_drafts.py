"""Synthetic, immutable record-level access foundation for Domestic and Export.

No live household, research, customer, consent, source license, transaction,
training material or approval can enter this adapter. Grants must originate
from an injected, trusted server-side snapshot; JWT roles alone NEVER entitle
an operator to inspect arbitrary case files. No grant-changing HTTP APIs exist.
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Iterable, Mapping
import re

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal

ENGINES = frozenset({"DOMESTIC", "EXPORT"})
_OP_ROLE = {"DOMESTIC": "domestic_ops", "EXPORT": "export_ops"}
_REF = re.compile(r"^DEMO-[A-Z0-9-]{1,48}$")


def _synthetic_ref(value: str) -> bool:
    return isinstance(value, str) and bool(_REF.fullmatch(value))


def _synthetic_subject(value: str) -> bool:
    return (isinstance(value, str) and value.startswith("synthetic-")
            and 12 <= len(value) <= 128 and value.isascii()
            and all(c.isalnum() or c in "-_" for c in value))


@dataclass(frozen=True, slots=True)
class ScopedGrant:
    subject: str
    role: str

    def __post_init__(self) -> None:
        if not _synthetic_subject(self.subject) or self.role not in _OP_ROLE.values():
            raise ValueError("only explicit synthetic operation grants are supported")


@dataclass(frozen=True, slots=True)
class ScopedDraft:
    ref: str
    engine: str
    owner_subject: str
    version: int
    grants: tuple[ScopedGrant, ...]
    source_ref: str | None = None

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.ref) or self.engine not in ENGINES
                or not _synthetic_subject(self.owner_subject)
                or type(self.version) is not int or self.version < 1
                or type(self.grants) is not tuple
                or any(not isinstance(g, ScopedGrant) for g in self.grants)
                or len({(g.subject, g.role) for g in self.grants}) != len(self.grants)
                or any(g.role != _OP_ROLE[self.engine] for g in self.grants)):
            raise ValueError("invalid immutable scoped synthetic draft")
        if self.engine == "DOMESTIC":
            if self.source_ref is not None:
                raise ValueError("Domestic case must not contain Export source")
        elif not _synthetic_ref(self.source_ref):
            raise ValueError("Export example requires synthetic source reference")

    def public_view(self) -> dict:
        # Return only a newly built JSON-compatible fixed evidence envelope.
        base = {
            "ref": self.ref, "engine": self.engine, "version": self.version,
            "status": "DRAFT_ONLY", "source": "SYNTHETIC_ONLY",
        }
        if self.engine == "DOMESTIC":
            base.update({
                "purpose_consent_verified": False,
                "expert_approved": False, "plan_accepted": False,
                "real_data": False,
            })
        else:
            base.update({
                "source_ref": self.source_ref, "source_rights_verified": False,
                "review_approved": False, "buyer_verified": False,
                "contracted": False, "real_data": False,
            })
        return base


class ScopedSyntheticDraftRegistry:
    """Immutable technical fixture catalogue; NOT an approved operational repository."""

    def __init__(self, records: Iterable[ScopedDraft]):
        catalogue: dict[tuple[str, str], ScopedDraft] = {}
        for record in records:
            if not isinstance(record, ScopedDraft):
                raise ValueError("only validated synthetic records can enter catalogue")
            key = record.engine, record.ref
            if key in catalogue:
                raise ValueError("duplicate engine/record identity")
            catalogue[key] = record
        self._catalogue: Mapping[tuple[str, str], ScopedDraft] = MappingProxyType(catalogue)

    def read(self, engine: str, ref: str, principal: Principal, *, as_owner: bool) -> dict | None:
        if (engine not in ENGINES or not _synthetic_ref(ref)
                or not isinstance(principal, Principal)
                or not isinstance(principal.subject, str)):
            return None
        record = self._catalogue.get((engine, ref))
        if record is None:
            return None
        if as_owner:
            if not (engine == "DOMESTIC"
                    and "household" in principal.roles
                    and principal.subject == record.owner_subject):
                return None
        else:
            required = _OP_ROLE[engine]
            if (required not in principal.roles
                    or not any(grant.subject == principal.subject and grant.role == required
                               for grant in record.grants)):
                return None
        return record.public_view()


def build_scoped_draft_router(
    registry: ScopedSyntheticDraftRegistry,
    principal_dependency: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(registry, ScopedSyntheticDraftRegistry):
        raise ValueError("explicit synthetic record catalogue required")
    router = APIRouter()

    def lookup(engine: str, ref: str, p: Principal, as_owner: bool) -> dict:
        result = registry.read(engine, ref, p, as_owner=as_owner)
        if result is None:
            # No record-enumeration oracle: absent, wrong role or unassigned
            # case are indistinguishable. A valid JWT remains necessary.
            raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
        return result

    @router.get("/api/v1/domestic/household-intake/drafts/{ref}")
    def own_domestic(ref: str, p: Principal = Depends(principal_dependency)) -> dict:
        return lookup("DOMESTIC", ref, p, as_owner=True)

    @router.get("/api/v1/admin/domestic/household-intake/drafts/{ref}")
    def assigned_domestic(ref: str, p: Principal = Depends(principal_dependency)) -> dict:
        return lookup("DOMESTIC", ref, p, as_owner=False)

    @router.get("/api/v1/admin/export/research/drafts/{ref}")
    def assigned_export(ref: str, p: Principal = Depends(principal_dependency)) -> dict:
        return lookup("EXPORT", ref, p, as_owner=False)

    return router
