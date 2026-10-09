# Read-only Product Discovery Contract — DRAFT 0.1

**Status:** technical proposal / not customer-facing marketplace. Source of capability vocabulary is solely Business D-01..D-10 / E-01..E-09.

## GET /healthz
Response 200: `{"status":"alive","scope":"design_only"}`. Process liveness **does not** imply Stage or Production readiness.

## GET /api/v1/product/engines
Response 200: array containing exactly `domestic` and `export` with `key`, `title_fa`, `source_ref`, `business_gate="OPEN"` and `capability_count`. Counts are 10 for domestic, 9 for export.

## GET /api/v1/product/engines/{engine_key}
Response 200: the same engine summary, plus `capabilities` list; each item contains:
- `code`: stable **business document reference** (e.g. `D-02`, `E-06`); not a public API policy ID
- `title_fa`: document-derived Persian feature name
- `source_ref`: path to the origin Business document
- `status="DESIGN_ONLY"`: not implemented, activated or approved for operations

Unknown engine returns HTTP 404 with `{"detail":"Unknown engine"}`.

## GET /api/v1/product/engines/{engine_key}/capabilities
Response 200: same capability array, for the **selected** engine only. No possibility to infer an engine from context or substitute export/domestic data.

## Not exposed
No user/account details, private enterprise data, API token, pricing/commission/FX fields, legal identity, payment status, verified QC or real export orders. No business mutations. A successful `GET` here is not evidence of implementation of D-01..D-10 / E-01..E-09.

## Versioning and revision
Changing Business vocabulary or activation semantics requires an explicit documented revision, tests and approval before corresponding operational APIs exist; the discovery format is itself a provisional v0.1 code contract.
