# Ronas — Actionable next-step navigation in the existing two workspaces

**LOCAL/TEST ONLY**, no new user environment, Business gate admission, service role, licence, approval or real data collection. Technical PR #9 continues to use only the existing signed Keycloak BFF, existing exact-case owner/assignment/grant reads, and the current separate audited domain mutation endpoints. Business issues #2 Domestic, #3 Export and #4 Finance remain OPEN.

## Journey 1 — household
On the existing owner-only case detail `GET /my-drafts/{ref}`, a second **authoritative owner-scoped current-input revision read** and (when mounted) the owner's private current expert-question/response read yield just a **next-page link**, never new command authority:
- No current outstanding question → owner may open the existing fixed DEMO input-manifest correction form, which still demands CSRF, Origin, signed owner, case version, expected input revision and writes only a hash.
- Latest question bound to the **current** input version with no reply → deep-link to existing owner-only response form. Historical/stale questions cannot be recycled as current prompts.
- Reply already stored → show that expert review is still pending, with a link to read-only owner response history. A response does not equal valid consent, adequate evidence, an approved plan or stage monitoring.

## Journey 2 — assigned agronomy specialist
Existing case detail `GET /agronomy/assigned-drafts/{ref}` adds a navigation card based only on the **separately authorized exact assignment** and the current proposal plus historical question/receipt read:
- Missing current structural proposal → review history only, no implied new advice.
- Current proposal but no question → link to the existing specialist review-question form.
- Current question unanswered → show waiting for household, with history link.
- Household receipt exists, not yet observed → link to the existing exact-identity inspection form.
- Receipt observed → explicitly label *not reviewed*. Expert never receives the household response/evidence payload.

The helper is only a rendering decision, not a command or business assessment. Stale/revoked case grants still yield 404; damaged or stale independent plan/source integrity fails closed at 503 instead of being silently treated as a normal history state. Mutating commands independently enforce same-transaction assignment, question/input revision CAS and append-only audit.

## Journey 3 — Export admin operator
Existing case detail `GET /admin/export/research/drafts/{ref}` labels the next **DEMO research-question form** according to persisted question revision:
- No local question → define initial synthetic DEMO product/destination references.
- Existing revision → revise synthetic references; source use rights, approved report, buyer and contract remain false. Navigate directly to current form without creating any real study or commerce.

Only current exact-case `export_ops` grants may read it; source-rights/real data never become accepted by a display widget. History revision mismatches fail closed.

## Tests / constraints
Pure function tests cover revision mismatch, stale input/question, receipt-present-versus-approved, denied source rights and no automatic progression. Signed browser integration tests cover owner, specialist and export paths, cross-actor denial, flow after writing a legitimate DEMO question/response/receipt, private response non-disclosure, and follow-on issue/failure. Form anchors are accessible links in a Persian RTL responsive navigation surface; no JavaScript, external network dependency, new database or migration. Original application defaults remain unmounted for BFF; prototype static HTML remains separate.

**Scope boundary:** no real personal data, consent, crop stage definitions, images, licensed dataset ingestion, production AI, market price, contract, payment or Stage/QA/Release/Production. These pointers do not imply a genuine accepted product workflow. This is a focused UX integration of already-authorized LOCAL/TEST flows, not a new synthetic event engine. Code Review is an automated COMMENT, not independent human approval.
