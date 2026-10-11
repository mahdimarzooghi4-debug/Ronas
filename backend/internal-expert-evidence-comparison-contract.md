# Ronas — Case-local historical synthetic evidence comparison (LOCAL/TEST)

**Status:** draft technical foundation, NOT approved real expert review or scientific evidence verification. Domestic #2, Export #3, Finance #4 remain OPEN; Business candidates D1-DATA-01/02, D1-SCI-01, D1-REV-01..04 remain unapproved. No real consent, model run or plan approval exists.

## Why not directly subtract two earlier handoff fingerprints?

The previous \`review-handoff-fingerprint\` is an ephemeral canonical hash incorporating LOCAL/TEST proposal/model/source candidate fixtures. Those fixtures are not themselves versioned in a durable historical source registry, and SHA-256 cannot be inverted to reconstruct old source/proposal objects. Claiming to compare those earlier full packets would fabricate evidence. This slice instead reconstructs **only the immutable, verified household-input/question/owner-response/receipt-sighting ledger** as of two case-local mutation boundaries. It explicitly reports that historical AI proposals and scientific source catalogues are **not reconstructible**.

## Two read-only specialist-only routes

- \`GET /api/v1/agronomy/assigned-drafts/{ref}/review-evidence-timeline\` returns the list of available **case-local evidence revision ordinals** (1..N), each event category and its input/question subject revision. These are not global SQLite audit sequences and reveal no other case's activity.
- \`GET /api/v1/agronomy/assigned-drafts/{ref}/review-evidence-compare?from_revision=X&to_revision=Y\` requires two genuine revisions of the same case with \`1 <= X < Y <= N\`. No arbitrary global sequence cursor, cross-case comparison, latest-current-source inference, approval, mutation or new persistence.

Each request verifies the entire existing shared append-only SQLite grant/case/input/question/response/sighting/audit ledger within the same transaction. Signed Keycloak expert role and current **exact case assignment** are required. Success appends **one** audited \`READ_ALLOWED\`, while the underlying evidence fingerprint excludes read audits. Unauthenticated 401, wrong engine/role/revoked case 404, invalid revisions 409, integrity corruption 503, never partial private disclosure. The default app does not mount these endpoints.

## The two compared immutable evidence snapshots

Each as-of boundary recomputes a **domain-separated, deterministic synthetic evidence SHA-256 fingerprint** over canonical input manifest revisions, question receipts and their synthetic pinned proposal/science manifest digests, household answer receipts and specialist sighting receipts recorded by that case up to the selected case-local event. Global audit sequence IDs are **excluded from returned payload and fingerprint**, so additional unrelated or read events do not change that structural identity.

The response gives both evidence fingerprints, latest input revision, exact per-track question/reply/sighting counts and latest question revision, and a **delta** separating input revision changes, added questions, newly received owner replies, newly sighted response receipts, and changes to the **pinned candidate** source manifest/proposal digest in the latest question per track. No actual earlier model state, source legal rights or content can be reconstructed from these digests; the delta is **not a scientific or legal source comparison**.

No private household answer/evidence refs, raw source/scientific content or rights-document IDs, note contents, stage instructions, model/run identifiers, original hash digests or global audit cursor leave the service. Three independent tracks remain \`NOT_REVIEWED\`, \`eligible_for_operational_reuse=false\`, and all actual consent, scientific legality, specialist qualification and plan activation flags false. Hashes are **not signatures or future replay approvals**.

This uses no new schema/table, no invented agronomy thresholds, no time-based retention, and no Stage/QA Gate/Release/Production. Both PR #1 and PR #9 remain Draft/Open/Unmerged and SQLite remains LOCAL/TEST only.
