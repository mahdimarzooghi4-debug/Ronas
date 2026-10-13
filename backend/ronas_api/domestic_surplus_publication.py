"""Version-bound Domestic surplus publication authorization (LOCAL/TEST core).

This module evaluates opaque, already-authorized evidence references. It does
not create market offers, define food-safety criteria, or publish listings.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Literal

from .scoped_drafts import _synthetic_ref

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ATTESTATION_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")

Blocker = Literal[
    "CURRENT_OFFER_UNAVAILABLE", "OFFER_VERSION_CHANGED",
    "PRODUCER_APPROVAL_REQUIRED", "PRODUCER_APPROVAL_STALE",
    "QUALITY_SAFETY_VERIFICATION_REQUIRED",
    "QUALITY_SAFETY_VERIFICATION_STALE", "OFFER_SCHEMA_CHANGED",
    "SELLER_ELIGIBILITY_UNVERIFIED", "HOUSEHOLD_PERMISSION_INACTIVE",
    "MARKETPLACE_GATE_CLOSED",
]


@dataclass(frozen=True, slots=True)
class OfferRevision:
    """Opaque exact offer content binding; no crop, quantity, or price invented."""
    offer_ref: str
    household_ref: str
    producer_subject: str
    revision: int
    payload_digest: str

    def __post_init__(self) -> None:
        if (not _synthetic_ref(self.offer_ref)
                or not _synthetic_ref(self.household_ref)
                or not isinstance(self.producer_subject, str)
                or not self.producer_subject or len(self.producer_subject) > 256
                or type(self.revision) is not int or self.revision < 1
                or not isinstance(self.payload_digest, str)
                or not _DIGEST.fullmatch(self.payload_digest)):
            raise ValueError("invalid Domestic offer revision")


@dataclass(frozen=True, slots=True)
class PublicationAttestation:
    """External authority's verified reference, never a user assertion."""
    attestation_ref: str
    offer_ref: str
    offer_revision: int
    payload_digest: str
    authority_kind: Literal["PRODUCER", "QUALITY_SAFETY"]
    authority_subject: str
    evidence_digest: str
    accepted: bool
    authority_verified: bool

    def __post_init__(self) -> None:
        if (not isinstance(self.attestation_ref, str)
                or not _ATTESTATION_REF.fullmatch(self.attestation_ref)
                or not _synthetic_ref(self.offer_ref)
                or type(self.offer_revision) is not int or self.offer_revision < 1
                or not isinstance(self.payload_digest, str)
                or not _DIGEST.fullmatch(self.payload_digest)
                or self.authority_kind not in ("PRODUCER", "QUALITY_SAFETY")
                or not isinstance(self.authority_subject, str)
                or not self.authority_subject or len(self.authority_subject) > 256
                or not isinstance(self.evidence_digest, str)
                or not _DIGEST.fullmatch(self.evidence_digest)
                or type(self.accepted) is not bool
                or type(self.authority_verified) is not bool):
            raise ValueError("invalid publication attestation")


@dataclass(frozen=True, slots=True)
class PublicationAuthorities:
    """Fresh external gate decisions. All gates default closed."""
    current_offer: OfferRevision | None = None
    producer_approval: PublicationAttestation | None = None
    quality_safety_verification: PublicationAttestation | None = None
    seller_eligibility_verified: bool = False
    household_permission_active: bool = False
    marketplace_gate_open: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.seller_eligibility_verified,
            self.household_permission_active,
            self.marketplace_gate_open,
        ):
            if type(value) is not bool:
                raise ValueError("publication gate flags must be strict booleans")
        if self.current_offer is not None and not isinstance(
                self.current_offer, OfferRevision):
            raise ValueError("current offer authority has invalid type")
        if self.producer_approval is not None and not isinstance(
                self.producer_approval, PublicationAttestation):
            raise ValueError("producer approval authority has invalid type")
        if self.quality_safety_verification is not None and not isinstance(
                self.quality_safety_verification, PublicationAttestation):
            raise ValueError("quality authority has invalid type")


@dataclass(frozen=True, slots=True)
class PublicationReadiness:
    offer_ref: str
    household_ref: str
    revision: int
    payload_digest: str
    readiness_digest: str
    state: str
    blockers: tuple[str, ...]
    can_publish: bool
    published: bool = False
    real_data: bool = False

    def as_dict(self) -> dict:
        return {
            "contract_version": "ronas.domestic.surplus-publication-gate.v2",
            "offer_ref": self.offer_ref,
            "household_ref": self.household_ref,
            "revision": self.revision,
            "payload_digest": self.payload_digest,
            "readiness_digest": self.readiness_digest,
            "state": self.state,
            "blockers": list(self.blockers),
            "can_publish": self.can_publish,
            "published": False,
            "real_data": False,
        }


def _same_revision(
    attestation: PublicationAttestation | None, offer: OfferRevision,
) -> bool:
    return bool(
        attestation is not None
        and attestation.offer_ref == offer.offer_ref
        and attestation.offer_revision == offer.revision
        and attestation.payload_digest == offer.payload_digest
        and attestation.accepted and attestation.authority_verified
    )


def evaluate_surplus_publication(
    proposed: OfferRevision, authorities: PublicationAuthorities,
    *, offer_schema_current: bool = True,
) -> PublicationReadiness:
    """Evaluate separate publication gates for one exact current version.

    A green result only means the supplied authorities permit a later publish
    command. This function never publishes or creates a public listing.
    """
    if (not isinstance(proposed, OfferRevision)
            or not isinstance(authorities, PublicationAuthorities)
            or type(offer_schema_current) is not bool):
        raise ValueError("versioned offer, schema state, and trusted authorities required")
    blockers: list[Blocker] = []
    current = authorities.current_offer
    if current is None:
        blockers.append("CURRENT_OFFER_UNAVAILABLE")
    elif (current.offer_ref != proposed.offer_ref
          or current.household_ref != proposed.household_ref
          or current.producer_subject != proposed.producer_subject
          or current.revision != proposed.revision
          or current.payload_digest != proposed.payload_digest):
        blockers.append("OFFER_VERSION_CHANGED")

    producer = authorities.producer_approval
    if producer is None or not producer.accepted or not producer.authority_verified:
        blockers.append("PRODUCER_APPROVAL_REQUIRED")
    elif (producer.authority_kind != "PRODUCER"
          or producer.authority_subject != proposed.producer_subject
          or not _same_revision(producer, proposed)):
        blockers.append("PRODUCER_APPROVAL_STALE")

    quality = authorities.quality_safety_verification
    if quality is None or not quality.accepted or not quality.authority_verified:
        blockers.append("QUALITY_SAFETY_VERIFICATION_REQUIRED")
    elif (quality.authority_kind != "QUALITY_SAFETY"
          or quality.authority_subject == proposed.producer_subject
          or not _same_revision(quality, proposed)):
        blockers.append("QUALITY_SAFETY_VERIFICATION_STALE")

    if not authorities.seller_eligibility_verified:
        blockers.append("SELLER_ELIGIBILITY_UNVERIFIED")
    if not authorities.household_permission_active:
        blockers.append("HOUSEHOLD_PERMISSION_INACTIVE")
    if not authorities.marketplace_gate_open:
        blockers.append("MARKETPLACE_GATE_CLOSED")

    if not offer_schema_current:
        blockers.append("OFFER_SCHEMA_CHANGED")

    can_publish = not blockers
    readiness_digest = hashlib.sha256(json.dumps(
        {
            "offer_ref": proposed.offer_ref,
            "household_ref": proposed.household_ref,
            "revision": proposed.revision,
            "payload_digest": proposed.payload_digest,
            "producer_attestation": (
                None if producer is None else {
                    "ref": producer.attestation_ref,
                    "evidence_digest": producer.evidence_digest,
                    "authority_subject": producer.authority_subject,
                }
            ),
            "quality_attestation": (
                None if quality is None else {
                    "ref": quality.attestation_ref,
                    "evidence_digest": quality.evidence_digest,
                    "authority_subject": quality.authority_subject,
                }
            ),
            "seller_eligibility_verified": authorities.seller_eligibility_verified,
            "household_permission_active": authorities.household_permission_active,
            "marketplace_gate_open": authorities.marketplace_gate_open,
            "offer_schema_current": offer_schema_current,
            "blockers": blockers,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return PublicationReadiness(
        offer_ref=proposed.offer_ref,
        household_ref=proposed.household_ref,
        revision=proposed.revision,
        payload_digest=proposed.payload_digest,
        readiness_digest=readiness_digest,
        state="PUBLICATION_AUTHORIZED" if can_publish else "NON_PUBLIC_DRAFT",
        blockers=tuple(blockers), can_publish=can_publish,
        # Public visibility is a separate write command and is never performed here.
        published=False,
    )
