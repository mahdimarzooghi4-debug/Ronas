# Ronas CORE-D1-A and CORE-E0-A executable foundation — DRAFT

Owner approved starting bounded first-slice work on 2026-10-10. This is a separate, non-operational proof of domain-boundary contracts. No Technical Architecture or software platform has been approved by the independent Business gates. Python 3.12 standard library is used solely to provide runnable, dependency-free validation experiments. It does not adopt or merge exploratory PR #6, or choose FastAPI as the Production stack.

CORE-D1-A has an in-memory, immutable intake draft constructor. It needs an explicit, purpose-matched consent reference; it refuses absent/declined consent and ambiguous or missing caller declarations. It never validates real identity, captures consent signatures, guarantees legal consent, chooses mandatory fields, assesses agricultural suitability, produces a crop plan, approves a household, retains data or grants sale eligibility.

CORE-E0-A has an in-memory, immutable research draft constructor. It requires human-supplied product, destination and question, a listed source with a rights caveat, and provenance for every research finding. The draft does not assert rights clearance or truth. It never chooses a market, verifies a buyer, issues an export commitment, trades, pays or ingests external data.

Neither module exposes a network endpoint, writes a file/database, sends data to third parties, uses personal/contractual data, loads an AI model or includes an actual human-approval authority. The tests are entirely synthetic; source names, household references and products in tests are placeholders, not real claims.

Run locally with Python 3.12:
  python -m unittest discover -s prototype/tests -v
  python -m compileall -q prototype/ronas_core

Reference: docs/business/70–74 on parent Business PR #1. Gates Domestic #2, Export #3 and Finance #4 remain OPEN. Before any real household data or customer-facing service, independently approve exact purpose-limited consent, fields, retention, rights, reviewer/authority, security/IAM, Technical Architecture and actual scoped Business Gate. Before any export research live use, obtain exact source rights, human-selected research scope, reviewer, and Export Gate. No deployment or merge without a separate explicit release action.
