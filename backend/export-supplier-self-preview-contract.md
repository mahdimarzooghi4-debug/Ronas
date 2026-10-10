# Export Supplier self-preview: LOCAL/TEST contract

Status: Draft PR #9. The approved UX topology provides a single shared user/partner environment for the `export_supplier` role. Business Export Gate #3 is OPEN; real onboarding, capacity declarations and transactions are not approved.

## Read-only user journey

The signed `export_supplier` can open `/workspace/export_supplier` and follow `/export-supplier/my-preview` when an explicit matching DEMO seed is available and currently authorized. The corresponding GET-only API is `/api/v1/export-supplier/my-preview`. Routes are opt-in and require an explicit Keycloak browser flow and `SyntheticSupplierWorkspace`. Default app has none of these routes.

The versioned `ronas.export-supplier.self-preview.v1` response contains only a DEMO reference, version, `NOT_SUBMITTED_DEMO`, `SYNTHETIC_ONLY`, and null placeholder fields for identity, products, capacity, availability, facility, and export permissions. All flags for identity, qualifications, capacity, rights, Export gate, business action, submission, buyer/contract, and real data are false. The UI never collects or persists a declaration. These placeholders are NOT an approved future input schema.

## Access boundaries

The server obtains the subject only from the Keycloak-verified Principal. The exact signed `export_supplier` role, a unique matching immutable `SyntheticSupplierPreviewSeed`, and literal `True` from the explicitly injected current `trusted_self_access` callback are required. Revocation takes effect on the next request. Missing/unauthorized identity or seed yields sanitized 404; unavailable checker yields 503; invalid token or revoked session yields 401. No client-provided subject or ref selects a profile. Other users, `export_ops`, `household`, `finance`, and `governance` cannot gain supplier self-access.

There is no identity or license verification, real consent, evidence rights check, active offering, buyer, trade, price, payment, report, algorithm or additional UI shell. The in-memory DEMO adapter has no durable write or standalone audit record and must NOT be represented as operational persistence or multi-replica authorization. HTML retains escaping, no-store, and CSP; all mutation verbs are unavailable.

## Validation and gates

15 new offline tests in `backend/tests/test_export_supplier_self_preview.py` check two-person isolation, exact role and seed, unknown fields, current access revocation, checker error/boolean strictness, signed JWT/cookie and logout, capability metadata, Persian UI visibility, default-off behavior, no HTTP mutation, and malformed/duplicate seed denial.

Business Gates #2 Domestic, #3 Export, and #4 Finance remain OPEN. PR #1/#9 stay Draft/Open/Unmerged. No Merge, Stage, QA, Release, Production, real supplier onboarding, capacity submission, or trade is authorized.
