# Ronas — Local Buyer and Equipment Seller Personal DEMO Previews

**Status:** LOCAL/TEST, read-only and opt-in within development Draft PR #9.
This is not operational domestic trade, buyer registration, equipment
listing, an offer, payment, consent, equipment certification, or inventory.

## The core shared-user journey

These are **two existing roles in the same shared user/partner environment**,
not separate user panels:

| Signed role | Shared role workspace | Personal HTML | Read-only API |
| --- | --- | --- | --- |
| `local_buyer` | `GET /workspace/local_buyer` | `GET /local-buyer/my-preview` | `GET /api/v1/local-buyer/my-preview` |
| `equipment_seller` | `GET /workspace/equipment_seller` | `GET /equipment-seller/my-preview` | `GET /api/v1/equipment-seller/my-preview` |

Only an explicitly **injected** `SyntheticDomesticPartnerWorkspace` may
expose these previews. A Keycloak-verified signed role alone never creates
a fixture or authorizes a view. The current-local-test authority explicitly
checks the **role, signed subject, exact DEMO profile reference and version**
on every API, role-page or HTML read. Literal Python `True` is required;
all other responses deny, exceptions return sanitized 503. Access to one
role/seed does not confer another role/seed—even if the same test subject has
both signed roles. No subject/ref selector or other-person directory exists.
No HTTP mutation commands are mounted.

For `local_buyer`, the explicitly synthetic display slots `identity`,
`requested_products`, `requested_quantity`, `delivery_location`,
`budget` are all `null`. For `equipment_seller`, `identity`,
`equipment_catalogue`, `stock`, `service_area`, and
`equipment_suitability` are all `null`. The fields are unknown
**presentation placeholders, not approved intake schemas** or mandatory
information, and they carry no commercial rules. No products, equipment
list, price, buyer demand, stock, order, contract, payment or real user exists.
`NOT_SUBMITTED_DEMO` is a display state, not registration or identity
verification. All consent, professional/product verification, suitability,
Domestic Business gate and commercial flags are `false`.

The API contract is `ronas.domestic-partner.self-preview.v1`; every result
contains only its own DEMO `profile_ref` and version, never subject, JWT
claims, source names or a list of other users. Unsupported/unknown role,
unseeded or revoked view => indistinguishable 404; provider outage => 503;
expired/invalid signed token or session => 401; POST/PATCH/PUT/DELETE => 405.
No optional background auto-injection or production runtime inclusion.

## Architecture and verification

`backend/ronas_api/domestic_partner_workspace.py` owns the immutable,
validated, per-role/per-subject seeds; `domestic_partner_api.py` is the
Keycloak-backed read-only route adapter. `app.py` admits it only when
explicitly injected with the same Keycloak browser configuration; the
existing `shared_workspaces.py` advertises the two read capabilities
**only** when enabled. `ui_bff.py` adds Persian RTL personal preview
pages and role links inside the original user environment, with CSP,
no-store, and current authorization checks.

`backend/tests/test_domestic_partner_self_preview.py`: 15 offline signed
Keycloak test cases covering distinct null-only fields, same-role owner
isolation, mixed and dual-role separation, role-only denial, current
revocation, exact literal-true authority, capability flags, Persian user
navigation, provider 503, logout and expired JWT, default-off/no mutations,
fixture validation, and unseeded denial.

**Out of scope:** real consent, provider license/identity, business gate
approval, buyer or seller onboarding, scientific/equipment certification,
real purchasing, real trading, stock, offers, payments, source rights, other
user environments or a Production SQL store.

Business Domestic #2, Export #3 and Finance #4 gates remain OPEN.
PR #1 and PR #9 must stay Draft/Open/Unmerged. No Stage, QA Gate,
Ready for Review, Merge, Release or Production is authorized.
