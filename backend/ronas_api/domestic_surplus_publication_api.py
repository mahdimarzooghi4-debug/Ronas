"""Owner-scoped read endpoint for Domestic surplus publication readiness."""
import sqlite3
from collections.abc import Callable
from dataclasses import replace

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from .auth import Principal
from .scoped_drafts import _synthetic_ref
from .domestic_surplus_publication import (
    OfferRevision, PublicationAuthorities, evaluate_surplus_publication,
)
from .domestic_surplus_drafts import SurplusDraftLedger, is_surplus_draft_ledger
from .domestic_surplus_producer_consent import (
    ProducerConsentConflict, ProducerConsentIntegrityError,
    SqliteSyntheticProducerConsentLedger,
)

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
    producer_consent_ledger: SqliteSyntheticProducerConsentLedger | None = None,
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
    if producer_consent_ledger is not None:
        try:
            producer_approval = producer_consent_ledger.publication_attestation(
                principal, proposed,
            )
        except LookupError as exc:
            raise HTTPException(404, detail="OFFER_NOT_FOUND") from exc
        except (ProducerConsentIntegrityError, sqlite3.Error, RuntimeError) as exc:
            raise HTTPException(
                503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
            ) from exc
        authorities = replace(authorities, producer_approval=producer_approval)
    try:
        result = evaluate_surplus_publication(
            proposed, authorities, offer_schema_current=schema_current,
            household_input_revision_state=input_revision_state,
        ).as_dict()
        if producer_consent_ledger is not None:
            receipt = producer_consent_ledger.current(
                principal, household_ref, offer_ref,
            )
            result["producer_consent_state"] = (
                "NOT_RECORDED" if receipt is None else receipt.state
            )
            result["producer_consent_revision"] = (
                0 if receipt is None else receipt.revision
            )
        return result
    except (ValueError, ProducerConsentIntegrityError, sqlite3.Error, RuntimeError) as exc:
        raise HTTPException(
            503, detail="PUBLICATION_AUTHORITY_UNAVAILABLE",
        ) from exc


def build_domestic_surplus_publication_router(
    authority: PublicationAuthority,
    verified_principal: Callable[..., Principal],
    draft_ledger: SurplusDraftLedger | None = None,
    input_revision_reader: InputRevisionReader | None = None,
    producer_consent_ledger: SqliteSyntheticProducerConsentLedger | None = None,
) -> APIRouter:
    """Mount only with a live, owner-scoped authority resolver."""
    if (not callable(authority) or not callable(verified_principal)
            or (draft_ledger is not None
                and not is_surplus_draft_ledger(draft_ledger))
            or input_revision_reader is not None
            and not callable(input_revision_reader)
            or producer_consent_ledger is not None
            and (not isinstance(producer_consent_ledger,
                                SqliteSyntheticProducerConsentLedger)
                 or producer_consent_ledger._draft_ledger is not draft_ledger)):
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
            input_revision_reader, producer_consent_ledger,
        )

    if producer_consent_ledger is not None:
        @router.post(
            "/api/v1/domestic/household-intake/my-drafts/{household_ref}/"
            "surplus-offers/{offer_ref}/producer-publication-consent",
            status_code=201,
        )
        async def record_producer_publication_consent(
            household_ref: str, offer_ref: str, request: Request,
            principal: Principal = Depends(verified_principal),
            authorization: str | None = Header(default=None),
        ) -> dict:
            if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
                raise HTTPException(401, detail="BEARER_TOKEN_REQUIRED")
            try:
                payload = await request.json()
            except Exception as exc:
                raise HTTPException(422, detail="INVALID_PRODUCER_CONSENT") from exc
            if (not isinstance(payload, dict)
                    or set(payload) != {"expected_offer_revision",
                                        "expected_payload_digest", "action_id",
                                        "approved"}
                    or type(payload.get("expected_offer_revision")) is not int
                    or not isinstance(payload.get("expected_payload_digest"), str)
                    or not isinstance(payload.get("action_id"), str)
                    or type(payload.get("approved")) is not bool):
                raise HTTPException(422, detail="INVALID_PRODUCER_CONSENT")
            try:
                result = producer_consent_ledger.record(
                    principal, household_ref, offer_ref,
                    expected_offer_revision=payload["expected_offer_revision"],
                    expected_payload_digest=payload["expected_payload_digest"],
                    action_id=payload["action_id"], approved=payload["approved"],
                )
            except ProducerConsentConflict as exc:
                raise HTTPException(409, detail="PRODUCER_CONSENT_STALE") from exc
            except LookupError as exc:
                raise HTTPException(404, detail="OFFER_NOT_FOUND") from exc
            except ProducerConsentIntegrityError as exc:
                raise HTTPException(503, detail="PRODUCER_CONSENT_INTEGRITY_FAILURE") from exc
            except (sqlite3.Error, RuntimeError) as exc:
                raise HTTPException(503, detail="PRODUCER_CONSENT_UNAVAILABLE") from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_PRODUCER_CONSENT") from exc
            return {
                "household_ref": result.household_ref,
                "offer_ref": result.offer_ref,
                "offer_revision": result.offer_revision,
                "payload_digest": result.payload_digest,
                "revision": result.revision, "state": result.state,
                "action_id": result.action_id,
                "receipt_digest": result.receipt_digest,
                "published": False, "real_data": False,
            }

    return router
