# Ronas — Shared User/Partner Role Workspace (LOCAL/TEST)

Status: **Technical read-only and synthetic**, not Business approval, a
role-qualification registry, user provisioning, real service access or
Production authorization. Recorded 2026-10-10 in Draft PR #9.

## Product boundary

Ronas has exactly two UI environments:

- Existing shared user/partner shell `/` for `household`,
  `local_buyer`, `agronomy_expert`, `equipment_seller`, and
  `export_supplier`
- Existing unified `/admin` shell for independent Domestic, Export,
  Finance and Governance admin domains

The new `/workspace/{role}` is a **detail route inside the same shared
user/partner environment**, not a separate panel, tenant or operational
workflow. The five canonical role labels are maintained in
`ronas_api/shared_workspaces.py` and reused by the UI and API. Roles are
taken only from an independently verified, signed Keycloak API-client token
or an existing server-side BFF session that revalidates that same token.
No `X-Role`, browser-supplied list, query or page link can activate a
role that is not in the verified principal.

## Contract

The **opt-in** browser application supports:

- `GET /api/v1/me/user-workspaces`
- `GET /api/v1/me/user-workspaces/{role}`
- `GET /workspace/{role}` (Persian RTL HTML role detail)
- Existing `GET /` cards include links to only the currently authenticated
  user's canonical shared-role details

API list entries contain only `role`, `label`,
`environment=SHARED_USER_PARTNER`, `activity_state=NOT_OPERATIONAL`,
`business_actions_enabled=false` and `local_test_reads`. No subject
identifier, personal record, grant authority, underlying token, claim
source or case count enters this projection.

`local_test_reads` truthfully reflects only *explicitly injected local*
read-only capabilities **for the household role**:

- With no synthetic SQLite scoped ledger: empty
- With an explicit `SqliteSyntheticGrantLedger`:
  `OWNED_SYNTHETIC_DOMESTIC_DRAFTS`
- With the **same** explicitly injected
  `SqliteSyntheticHumanReviewLedger` used for exact-case grants and
  technical history: also `OWNED_SYNTHETIC_TECHNICAL_PROGRESS`

These flags are **not** case grants, permission to open other owners'
records, entitlement to a Business service or assertion that even one
case exists. Every actual case read continues to require the existing
independently verified owner/grant check in its own transactional ledger
contract. Non-household partner roles have an empty list of local
case reads; the fact of holding such a role does not license or qualify
a buyer, agronomist, equipment merchant or export supplier.

Missing/invalid signed authentication is HTTP 401. Unknown and unassigned
role details are both 404 `WORKSPACE_NOT_FOUND`, without an
enumeration oracle. HTTP POST is not supported. The server-rendered
role page always states operational activity is disabled, escapes
canonical labels, retains strict same-origin CSP and `no-store`, and
links to synthetic owned household cases only if that exact local
owner-view capability is explicitly wired. Logout or an expired
Keycloak token denies future reads.

## Admission and exclusions

`create_app` mounts these API routes and the shared user HTML only when
an explicit `BrowserOIDC` is injected **and** its KeycloakConfig exactly
matches the app. The default app without browser injection exposes no
role-workspace API or UI. It creates no synthetic user, external IdP,
new role, admin panel, case, payment, purchase, export transaction,
expert-qualification decision or AI-produced plan.

Dedicated offline tests:
`backend/tests/test_shared_user_workspaces.py` — 16 scenarios for all
five canonical partner roles, signed bearer and cookie credentials,
multi-role navigation, denial parity, spoofing, invalid/expired tokens,
logout, default-disabled endpoints, correct live opt-in read metadata,
HTML security headers and absence of write routes. Uses only ephemeral
locally generated signing keys and synthetic principals; no real Keycloak
or customer/case data.

Domestic Business #2, Export Business #3 and Finance Business #4 remain
OPEN. PR #1 and PR #9 stay Draft/Open/Unmerged. No Stage/QA Gate,
Release approval or Production deployment has been authorized.
