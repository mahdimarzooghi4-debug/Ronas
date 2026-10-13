"""Owner-scoped read endpoint for Domestic surplus publication readiness."""
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal
from .scoped_drafts import _synthetic_ref
from .domestic_surplus_publication import (
    OfferRevision, PublicationAuthorities, evaluate_surplus_publication,
)

PublicationAuthority = Callable[
    [Principal, str, str],
    tuple[OfferRevision, PublicationAuthorities] | None,
]


def build_domestic_surplus_publication_router(
    authority: PublicationAuthority,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    """Mount only with a live, owner-scoped authority resolver."""
    if not callable(authority) or not callable(verified_principal):
        raise ValueError("trusted publication and identity authorities required")
    router = APIRouter()

    @router.get(
        "/api/v1/domestic/household-intake/my-drafts/{household_ref}/"
        "surplus-offers/{offer_ref}/publication-readiness",
    )
    def publication_readiness(
        household_ref: str, offer_ref: str,
        principal: Principal = Depends(verified_principal),
    ) -> dict:
        if (not isinstance(principal, Principal)
                or "household" not in principal.roles
                or not _synthetic_ref(household_ref)
                or not _synthetic_ref(offer_ref)):
            raise HTTPException(404, detail="OFFER_NOT_FOUND")
        try:
            snapshot = authority(principal, household_ref, offer_ref)
        except Exception as exc:
            raise HTTPException(
                503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
            ) from exc
        if snapshot is None or not isinstance(snapshot, tuple) or len(snapshot) != 2:
            raise HTTPException(404, detail="OFFER_NOT_FOUND")
        offer, authorities = snapshot
        if (not isinstance(offer, OfferRevision)
                or offer.household_ref != household_ref
                or offer.offer_ref != offer_ref
                or offer.producer_subject != principal.subject
                or not isinstance(authorities, PublicationAuthorities)):
            # Do not reveal whether a different household or offer exists.
            raise HTTPException(404, detail="OFFER_NOT_FOUND")
        try:
            return evaluate_surplus_publication(offer, authorities).as_dict()
        except ValueError as exc:
            raise HTTPException(
                503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
            ) from exc

    return router
