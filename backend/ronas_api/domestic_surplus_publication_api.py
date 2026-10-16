"""Owner-scoped read endpoint for Domestic surplus publication readiness."""
import sqlite3
from collections.abc import Callable
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal
from .scoped_drafts import _synthetic_ref
from .domestic_surplus_publication import (
    OfferRevision, PublicationAuthorities, evaluate_surplus_publication,
)
from .domestic_surplus_drafts import SurplusDraftLedger, is_surplus_draft_ledger

PublicationAuthority = Callable[
    [Principal, str, str],
    tuple[OfferRevision, PublicationAuthorities] | None,
]
InputRevisionReader = Callable[[str, Principal], dict | None]


def publication_readiness_snapshot(
    authority: PublicationAuthority,
    principal: Principal,
    household_ref: str,
    offer_ref: str,
    draft_ledger: SurplusDraftLedger | None = None,
    input_revision_reader: InputRevisionReader | None = None,
) -> dict:
    """One owner and version check shared by API and authenticated UI."""
    if (not isinstance(principal, Principal)
            or "household" not in principal.roles
            or not _synthetic_ref(household_ref)
            or not _synthetic_ref(offer_ref)):
        raise HTTPException(404, detail="OFFER_NOT_FOUND")
    persisted_offer = None
    schema_current = True
    input_revision_state = "NOT_TRACKED"

    def current_input_state(draft) -> str:
        if draft.input_revision is None:
            return "UNBOUND"
        if input_revision_reader is None:
            return "UNAVAILABLE"
        try:
            snapshot = input_revision_reader(household_ref, principal)
        except Exception as exc:
            raise HTTPException(
                503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
            ) from exc
        if snapshot is None:
            raise HTTPException(404, detail="OFFER_NOT_FOUND")
        revision = snapshot.get("current_input_revision")
        if revision is not None and (type(revision) is not int or revision < 1):
            raise HTTPException(
                503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
            )
        return "CURRENT" if revision == draft.input_revision else "CHANGED"

    if draft_ledger is not None:
        try:
            draft = draft_ledger.read_owned(principal, household_ref, offer_ref)
        except LookupError as exc:
            raise HTTPException(404, detail="OFFER_NOT_FOUND") from exc
        except (RuntimeError, sqlite3.Error) as exc:
            raise HTTPException(
                503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
            ) from exc
        persisted_offer = OfferRevision(
            draft.offer_ref, draft.household_ref, draft.producer_subject,
            draft.revision, draft.payload_digest,
        )
        schema_current = draft.schema_digest == draft_ledger.schema.digest
        input_revision_state = current_input_state(draft)
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
        raise HTTPException(404, detail="OFFER_NOT_FOUND")
    proposed = offer if persisted_offer is None else persisted_offer
    if persisted_offer is not None:
        if offer != persisted_offer:
            # Conflicting resolver and durable draft snapshots fail closed as stale.
            authorities = replace(authorities, current_offer=offer)
        try:
            latest_draft = draft_ledger.read_owned(
                principal, household_ref, offer_ref,
            )
        except LookupError as exc:
            raise HTTPException(404, detail="OFFER_NOT_FOUND") from exc
        except (RuntimeError, sqlite3.Error) as exc:
            raise HTTPException(
                503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
            ) from exc
        latest_offer = OfferRevision(
            latest_draft.offer_ref, latest_draft.household_ref,
            latest_draft.producer_subject, latest_draft.revision,
            latest_draft.payload_digest,
        )
        schema_current = latest_draft.schema_digest == draft_ledger.schema.digest
        input_revision_state = current_input_state(latest_draft)
        if latest_offer != persisted_offer:
            # The draft changed while external authorities were being resolved.
            # Keep the original candidate, but force evaluation against the new version.
            authorities = replace(authorities, current_offer=latest_offer)
    try:
        return evaluate_surplus_publication(
            proposed, authorities, offer_schema_current=schema_current,
            household_input_revision_state=input_revision_state,
        ).as_dict()
    except ValueError as exc:
        raise HTTPException(
            503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
        ) from exc


def build_domestic_surplus_publication_router(
    authority: PublicationAuthority,
    verified_principal: Callable[..., Principal],
    draft_ledger: SurplusDraftLedger | None = None,
    input_revision_reader: InputRevisionReader | None = None,
) -> APIRouter:
    """Mount only with a live, owner-scoped authority resolver."""
    if (not callable(authority) or not callable(verified_principal)
            or (draft_ledger is not None
                and not is_surplus_draft_ledger(draft_ledger))
            or input_revision_reader is not None
            and not callable(input_revision_reader)):
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
        return publication_readiness_snapshot(
            authority, principal, household_ref, offer_ref, draft_ledger,
            input_revision_reader,
        )

    return router
