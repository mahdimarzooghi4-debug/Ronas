"""Export source connector boundary for ephemeral snapshot fingerprinting.

Connectors return bytes only to the caller in memory. Ronas stores only the
SHA-256 digest and opaque evidence reference in its append-only ledger.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
from typing import Protocol

from .auth import Principal
from .export_research_evidence import (
    ExportEvidenceReferenceConflict, valid_evidence_refs,
)
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger
from .scoped_drafts import _synthetic_ref

MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


class ExportSourceConnectorUnavailable(RuntimeError):
    """A configured source connector failed or returned an invalid snapshot."""


@dataclass(frozen=True, slots=True)
class ExportSourceSnapshot:
    evidence_ref: str
    content: bytes


class ExportSourceConnector(Protocol):
    connector_ref: str

    def fetch_snapshot(
        self, *, source_ref: str, product_ref: str, destination_ref: str,
    ) -> ExportSourceSnapshot: ...


class ExportSourceConnectorRegistry:
    """Explicit connector allowlist; no URL, hostname, or client-selected path."""

    def __init__(self, connectors: Iterable[ExportSourceConnector]) -> None:
        items: dict[str, ExportSourceConnector] = {}
        for connector in connectors:
            ref = getattr(connector, "connector_ref", None)
            if (not isinstance(ref, str) or not _synthetic_ref(ref)
                    or not ref.startswith("DEMO-CONNECTOR-")
                    or not callable(getattr(connector, "fetch_snapshot", None))
                    or ref in items):
                raise ValueError("invalid or duplicate Export source connector")
            items[ref] = connector
        self._connectors = items

    def fetch(
        self, connector_ref: str, *, source_ref: str,
        product_ref: str, destination_ref: str,
    ) -> ExportSourceSnapshot:
        connector = self._connectors.get(connector_ref)
        if connector is None:
            raise ValueError("unknown Export source connector")
        if (not _synthetic_ref(source_ref)
                or not _synthetic_ref(product_ref)
                or not _synthetic_ref(destination_ref)):
            raise ValueError("invalid connector query scope")
        try:
            snapshot = connector.fetch_snapshot(
                source_ref=source_ref, product_ref=product_ref,
                destination_ref=destination_ref,
            )
        except Exception as exc:
            raise ExportSourceConnectorUnavailable(
                "Export source connector failed",
            ) from exc
        if (not isinstance(snapshot, ExportSourceSnapshot)
                or not valid_evidence_refs(snapshot.evidence_ref, connector_ref)
                or not isinstance(snapshot.content, bytes)
                or not 1 <= len(snapshot.content) <= MAX_SNAPSHOT_BYTES):
            raise ExportSourceConnectorUnavailable(
                "Export source connector returned invalid snapshot",
            )
        return snapshot


def capture_export_source_reference(
    ledger: SqliteSyntheticHumanReviewLedger,
    connectors: ExportSourceConnectorRegistry,
    ref: str,
    principal: Principal,
    *,
    expected_case_version: int,
    expected_question_revision: int,
    expected_evidence_revision: int,
    action_id: str,
    connector_ref: str,
) -> dict | None:
    """Fetch current-question snapshot transiently, hash it, persist no bytes."""
    if (not isinstance(ledger, SqliteSyntheticHumanReviewLedger)
            or not isinstance(connectors, ExportSourceConnectorRegistry)):
        raise ValueError("explicit Export ledger and connector registry required")
    workspace = ledger.read_export_research_workspace(ref, principal)
    if workspace is None:
        return None
    question = workspace["local_test_draft_question"]
    if (workspace["case_version"] != expected_case_version
            or question is None
            or question["question_revision"] != expected_question_revision):
        raise ExportEvidenceReferenceConflict("Export question context changed")
    current_evidence_revision = sum(
        1 for item in workspace["local_test_evidence_references"]
        if item["question_revision"] == expected_question_revision
    )
    if expected_evidence_revision != current_evidence_revision:
        raise ExportEvidenceReferenceConflict("Export evidence revision changed")
    snapshot = connectors.fetch(
        connector_ref, source_ref=workspace["source_ref"],
        product_ref=question["product_ref"],
        destination_ref=question["destination_ref"],
    )
    digest = hashlib.sha256(snapshot.content).hexdigest()
    # No connector bytes cross the persistence boundary.
    return ledger.record_export_evidence_reference(
        ref, principal,
        expected_case_version=expected_case_version,
        expected_question_revision=expected_question_revision,
        expected_evidence_revision=expected_evidence_revision,
        action_id=action_id, evidence_ref=snapshot.evidence_ref,
        connector_ref=connector_ref, source_snapshot_digest=digest,
    )
