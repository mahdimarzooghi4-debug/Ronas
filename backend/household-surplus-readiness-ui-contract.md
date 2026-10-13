# Household surplus readiness workspace (LOCAL/TEST)

## Goal

Expose the existing version-bound surplus publication readiness result inside the authenticated household environment. The workspace is a read-only view of the current owner's own offer readiness. It must not create, publish, list, sell, or expose offers to buyers.

## Composition

- Propagate the optional `household_surplus_publication_authority` resolver through the SQLite and PostgreSQL LOCAL/TEST Keycloak BFF factory functions to `create_app`.
- Reuse the exact household profile ledger, profile schema, browser flow, signed household role, and existing profile access authority already required by `create_app`. Reject a mismatched or incomplete composition before serving routes.
- Keep the resolver absent by default. When absent, do not mount the readiness route or render a readiness link.
- Use the existing household workspace and its current session/CSRF protections. The readiness request is GET-only and must not introduce a new write command or cookie-authenticated mutation.

## Read view

The existing household draft page may link to a Persian RTL readiness view for an explicitly referenced DEMO offer. The view calls the owner-scoped readiness endpoint and displays only its public projection: current state, whether publication requirements are satisfied, and blocker codes translated to fixed Persian labels. It must never display authority subjects, evidence digests, private documents, household profile contents, or resolver errors.

The page must state that `PUBLICATION_AUTHORIZED` is technical readiness only. It must not say that the offer is published, visible to buyers, available for purchase, quality-approved, or financially actionable. `published` remains false. Unknown blocker codes render as a generic unavailable state and are not interpolated into HTML.

## Security and consistency

- The API remains owner-scoped; cross-household references return the existing non-enumerating not-found response.
- UI navigation is role-gated by the authenticated household session. Server-side authorization remains authoritative.
- Readiness is fetched fresh on each page request; do not cache it across sessions or offer revisions.
- Fail closed on resolver errors, invalid refs, missing browser/profile authorities, or mismatched ledgers.
- Preserve no-store response headers and HTML escaping. No raw offer data is accepted by this view.

## Tests

1. SQLite and PostgreSQL BFF compositions forward the exact injected resolver to the same app factory.
2. An absent resolver leaves route and UI link unavailable.
3. Valid household owner can see only the safe readiness projection in Persian RTL.
4. Wrong role and cross-household access do not reveal offer existence or private evidence.
5. Resolver exception renders a generic unavailable state without leaking its message.
6. No code path changes `published=false` or creates marketplace records.

## Boundary

This contract defines a LOCAL/TEST integration slice. It does not implement publication, quality rules, seller qualification, consent, trading, pricing, settlement, or Production activation.
