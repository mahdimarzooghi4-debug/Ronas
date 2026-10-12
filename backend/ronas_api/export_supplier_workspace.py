"""LOCAL/TEST self-owned Export supplier preparation preview.

This is NOT an identity verification, lawful supplier onboarding, capacity
declaration, trade eligibility or producer offer. Every commercial field is
unknown; the fixed DEMO fixtures never represent real people or goods.
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Iterable

from .auth import Principal
from .scoped_drafts import _synthetic_ref, _synthetic_subject

CONTRACT_VERSION = "ronas.export-supplier.self-preview.v1"


class SyntheticSupplierUnavailable(RuntimeError):
    """Current test fixture authorization could not be evaluated."""


@dataclass(frozen=True, slots=True)
class SyntheticSupplierPreviewSeed:
    ref: str
    subject: str
    version: int

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.ref)
                or not _synthetic_subject(self.subject)
                or type(self.version) is not int or self.version < 1):
            raise ValueError("invalid synthetic supplier profile seed")


class SyntheticSupplierWorkspace:
    """Independent, opt-in self-view, NEVER an export_ops case grant."""

    def __init__(
        self, seeds: Iterable[SyntheticSupplierPreviewSeed], *,
        trusted_self_access: Callable[[str, str, int], bool],
    ) -> None:
        if not callable(trusted_self_access):
            raise ValueError("explicit current LOCAL/TEST self-access checker required")
        by_owner: dict[str, SyntheticSupplierPreviewSeed] = {}
        seen_refs: set[str] = set()
        for seed in seeds:
            if not isinstance(seed, SyntheticSupplierPreviewSeed):
                raise ValueError("untrusted supplier fixture")
            if seed.subject in by_owner or seed.ref in seen_refs:
                raise ValueError("duplicate synthetic supplier seed")
            by_owner[seed.subject] = seed
            seen_refs.add(seed.ref)
        self._seeds = MappingProxyType(by_owner)
        self._current_access = trusted_self_access

    def own_preview(self, principal: Principal) -> dict | None:
        if (not isinstance(principal, Principal)
                or not _synthetic_subject(principal.subject)
                or "export_supplier" not in principal.roles):
            return None
        # No profile selector, other-user lookup, supplier search or cross-engine
        # read. The only selection input is the *verified signed* subject.
        seed = self._seeds.get(principal.subject)
        if seed is None:
            return None
        try:
            allowed = self._current_access(
                principal.subject, seed.ref, seed.version,
            )
        except Exception as exc:
            raise SyntheticSupplierUnavailable("supplier self-access unavailable") from exc
        if allowed is not True:
            return None
        return {
            "contract_version": CONTRACT_VERSION,
            "environment": "SHARED_USER_PARTNER",
            "role": "export_supplier",
            "profile_ref": seed.ref,
            "profile_version": seed.version,
            "profile_state": "NOT_SUBMITTED_DEMO",
            "source": "SYNTHETIC_ONLY",
            "supplier_fields": {
                "identity": None,
                "products": None,
                "capacity": None,
                "availability": None,
                "facility": None,
                "export_permissions": None,
            },
            "identity_verified": False,
            "professional_status_verified": False,
            "capacity_verified": False,
            "source_and_trade_rights_verified": False,
            "export_gate_approved": False,
            "commercial_actions_enabled": False,
            "data_submission_enabled": False,
            "buyer_or_contract_exists": False,
            "real_data": False,
        }
