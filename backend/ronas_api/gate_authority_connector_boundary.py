"""Non-executing external-authority integration boundary (LOCAL/TEST).

This is a *future* connector contract and version-bound pending-request
identity, not a provider client. No authority has been selected or approved.
No provider response can be accepted or a Business Gate automatically passed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .business_gate_evidence import BUSINESS_SOURCE_SHA, DOSSIERS
from .gate_evidence_authority_enquiry_sqlite import CHECKS
from .gate_evidence_handoff_sqlite import canonical, digest


CONTRACT_VERSION = "ronas.authority.request.v1"
CONNECTOR_STATE = "NO_AUTHORITY_APPROVED"
UNRESOLVED_ADMISSION = (
    "AUTHORITY_IDENTITY_AND_TRUST_NOT_APPROVED",
    "PURPOSE_CONSENT_SOURCE_RIGHTS_NOT_APPROVED",
    "RESPONSE_AUTHENTICITY_AND_REPLAY_POLICY_NOT_APPROVED",
    "REVIEWER_CREDENTIAL_AND_APPOINTMENT_NOT_APPROVED",
    "DATA_HANDLING_RETENTION_NOT_APPROVED",
    "EXPLICIT_BUSINESS_DECISION_NOT_GRANTED",
)


class AuthorityConnectorNotAdmitted(RuntimeError):
    """External dispatch and response admission have no approved contract."""


@dataclass(frozen=True, slots=True)
class AuthorityRequestIdentity:
    domain: str
    evidence_id: str
    check_kind: str
    business_source_sha: str
    original_handoff_action: str
    original_handoff_digest: str
    enquiry_action: str
    enquiry_event_digest: str
    request_reference: str
    enquiry_revision: int
    contract_version: str = CONTRACT_VERSION

    @property
    def fingerprint(self) -> str:
        """Deterministic *local* lineage fingerprint, not a trusted signature."""
        return digest(canonical({
            "contract_version": self.contract_version,
            "business_source_sha": self.business_source_sha,
            "domain": self.domain,
            "evidence_id": self.evidence_id,
            "check_kind": self.check_kind,
            "original_handoff_action": self.original_handoff_action,
            "original_handoff_digest": self.original_handoff_digest,
            "enquiry_action": self.enquiry_action,
            "enquiry_event_digest": self.enquiry_event_digest,
            "request_reference": self.request_reference,
            "enquiry_revision": self.enquiry_revision,
        }))


class FutureAuthorityPort(Protocol):
    """Non-instantiated interface; implementations cannot be admitted here."""

    def exchange(self, request: AuthorityRequestIdentity) -> object:
        """Future contract deliberately has NO accepted response type yet."""


def pending_identity(*, handoff, enquiry) -> AuthorityRequestIdentity:
    """Bind exactly the persisted *request* to its original handoff event."""
    if (
        handoff.stage != "REFERENCE_RECORDED"
        or enquiry.stage != "CHECK_REFERENCE_REQUESTED"
        or enquiry.check_kind not in CHECKS
        or enquiry.domain != handoff.domain
        or enquiry.evidence_id != handoff.evidence_id
        or enquiry.source_action_id != handoff.action_id
        or enquiry.source_event_digest != handoff.event_digest
        or enquiry.revision != 1
        or not any(
            d.domain == enquiry.domain
            and any(e.evidence_id == enquiry.evidence_id for e in d.evidence)
            for d in DOSSIERS
        )
    ):
        raise AuthorityConnectorNotAdmitted("stale or invalid enquiry lineage")
    return AuthorityRequestIdentity(
        domain=enquiry.domain,
        evidence_id=enquiry.evidence_id,
        check_kind=enquiry.check_kind,
        business_source_sha=BUSINESS_SOURCE_SHA,
        original_handoff_action=handoff.action_id,
        original_handoff_digest=handoff.event_digest,
        enquiry_action=enquiry.action_id,
        enquiry_event_digest=enquiry.event_digest,
        request_reference=enquiry.request_ref,
        enquiry_revision=enquiry.revision,
    )


def blocked_connector_status(domain: str, evidence_id: str, check_kind: str,
                             technical_stage: str) -> dict:
    """Read-only honest capability status; never an authority qualification."""
    return {
        "domain": domain,
        "evidence_id": evidence_id,
        "check_kind": check_kind,
        "technical_state": technical_stage,
        "connector_state": CONNECTOR_STATE,
        "contract_version": CONTRACT_VERSION,
        "business_source_sha": BUSINESS_SOURCE_SHA,
        "dispatch_authorized": False,
        "provider_response_trusted": False,
        "rights_verified": False,
        "reviewer_qualification_verified": False,
        "business_gate_passed": False,
        "unresolved": list(UNRESOLVED_ADMISSION),
    }


def dispatch_unadmitted(
    request: AuthorityRequestIdentity, *, port: FutureAuthorityPort | None = None,
) -> None:
    """Always fail closed; a mock/provider object is NOT approval or identity."""
    # Do not even evaluate an injected port, as this would allow an
    # unapproved network exchange, side effect or remote data disclosure.
    raise AuthorityConnectorNotAdmitted("no authorized authority connector")


def accept_unadmitted_response(
    request: AuthorityRequestIdentity, response: object,
) -> None:
    """Always fail closed; even correctly shaped responses have no trust root."""
    raise AuthorityConnectorNotAdmitted("no approved response verification policy")
