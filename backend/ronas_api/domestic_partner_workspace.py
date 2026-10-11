"""LOCAL/TEST opt-in personal preparation previews for Domestic partner roles.

Synthetic fixtures NEVER represent people, offers, inventory, demand, orders,
equipment suitability, acceptance, financial data or production enrollment.
One role's seed/current authorization cannot grant the other role's view.
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Iterable

from .auth import Principal
from .scoped_drafts import _synthetic_ref, _synthetic_subject

ROLES = ("local_buyer", "equipment_seller")
CONTRACT_VERSION = "ronas.domestic-partner.self-preview.v1"
FIELDS = {
    "local_buyer": ("identity", "requested_products", "requested_quantity",
                    "delivery_location", "budget"),
    "equipment_seller": ("identity", "equipment_catalogue", "stock",
                         "service_area", "equipment_suitability"),
}


class SyntheticDomesticPartnerUnavailable(RuntimeError):
    """Current LOCAL/TEST self-access authority could not be checked."""


@dataclass(frozen=True, slots=True)
class SyntheticDomesticPartnerSeed:
    role: str
    ref: str
    subject: str
    version: int

    def __post_init__(self) -> None:
        if (self.role not in ROLES
                or not _synthetic_ref(self.ref)
                or not _synthetic_subject(self.subject)
                or type(self.version) is not int or self.version < 1):
            raise ValueError("invalid synthetic Domestic partner seed")


class SyntheticDomesticPartnerWorkspace:
    """Opt-in isolated read model; no household ownership/Export grant."""

    def __init__(
        self, seeds: Iterable[SyntheticDomesticPartnerSeed], *,
        trusted_self_access: Callable[[str, str, str, int], bool],
    ) -> None:
        if not callable(trusted_self_access):
            raise ValueError("explicit live LOCAL/TEST partner authority required")
        by_role_subject: dict[tuple[str, str], SyntheticDomesticPartnerSeed] = {}
        seen_refs: set[str] = set()
        for seed in seeds:
            if not isinstance(seed, SyntheticDomesticPartnerSeed):
                raise ValueError("untrusted partner seed")
            key = seed.role, seed.subject
            if key in by_role_subject or seed.ref in seen_refs:
                raise ValueError("duplicate synthetic Domestic partner seed")
            by_role_subject[key] = seed
            seen_refs.add(seed.ref)
        self._seeds = MappingProxyType(by_role_subject)
        self._live_access = trusted_self_access

    def own_preview(self, role: str, principal: Principal) -> dict | None:
        if (role not in ROLES
                or not isinstance(principal, Principal)
                or not _synthetic_subject(principal.subject)
                or role not in principal.roles):
            return None
        seed = self._seeds.get((role, principal.subject))
        if seed is None:
            return None
        try:
            allowed = self._live_access(
                role, principal.subject, seed.ref, seed.version,
            )
        except Exception as exc:
            raise SyntheticDomesticPartnerUnavailable(
                "Domestic partner self-access unavailable"
            ) from exc
        if allowed is not True:
            return None
        return {
            "contract_version": CONTRACT_VERSION,
            "environment": "SHARED_USER_PARTNER",
            "engine": "DOMESTIC",
            "role": role,
            "profile_ref": seed.ref,
            "profile_version": seed.version,
            "profile_state": "NOT_SUBMITTED_DEMO",
            "source": "SYNTHETIC_ONLY",
            "preparation_fields": {field: None for field in FIELDS[role]},
            "identity_verified": False,
            "purpose_consent_verified": False,
            "product_or_equipment_verified": False,
            "suitability_verified": False,
            "domestic_gate_approved": False,
            "data_submission_enabled": False,
            "commercial_actions_enabled": False,
            "order_or_offer_exists": False,
            "payment_enabled": False,
            "real_data": False,
        }

    def own_preparation_overview(self, principal: Principal) -> dict:
        """Read only this signed subject's independently permitted DEMO roles.

        The list is NOT a matchmaking or cross-actor export. Each role gets
        its own current authority check. Missing/denied seeds disappear
        without revealing their identifiers or counts. Authority failures
        fail the *entire* response rather than returning partial exposure.
        """
        items: list[dict] = []
        for role in ROLES:
            preview = self.own_preview(role, principal)
            if preview is None:
                continue
            fields = preview["preparation_fields"]
            # This is a presentation inventory of NULL DEMO placeholders,
            # not a Business completeness threshold or permission checklist.
            if (preview["profile_state"] != "NOT_SUBMITTED_DEMO"
                    or preview["commercial_actions_enabled"] is not False
                    or preview["data_submission_enabled"] is not False
                    or tuple(fields) != FIELDS[role]
                    or any(value is not None for value in fields.values())):
                raise SyntheticDomesticPartnerUnavailable(
                    "invalid synthetic partner preparation projection"
                )
            items.append({
                "role": role,
                "profile_ref": preview["profile_ref"],
                "profile_version": preview["profile_version"],
                "profile_state": preview["profile_state"],
                "unknown_display_slots": list(fields),
                "business_readiness": "NOT_EVALUATED",
                "commercial_actions_enabled": False,
                "data_submission_enabled": False,
            })
        return {
            "contract_version": "ronas.domestic-partner.preparation-overview.v1",
            "environment": "SHARED_USER_PARTNER",
            "engine": "DOMESTIC",
            "source": "SYNTHETIC_ONLY",
            "items": items,
            "business_readiness": "NOT_EVALUATED",
            "commercial_actions_enabled": False,
            "data_submission_enabled": False,
            "counterpart_matching_enabled": False,
            "real_data": False,
        }
