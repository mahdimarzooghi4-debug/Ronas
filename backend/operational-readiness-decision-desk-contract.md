# Ronas operational decision-readiness desk — read-only contract

**LOCAL/TEST, DRAFT SOURCE REVIEW ONLY — NO GATE PASS.** This is a next-decision worklist, not a live source-rights validation service, evidence intake, scientific plan approval, financial model or release admission.

## Integration

The existing single authenticated management environment now offers separate Domestic, Export and Finance decision-readiness pages. Five unchanged Business PR #1 draft sources at reviewed head 9bcc0f41e492b6e886b09cddff436da922cb616f are copied byte-identically onto stacked Technical PR #9 without merging either PR. The two previously pinned source dossiers and the separate FIN-002 source arithmetic remain intact. Git blob hashes of the five new sources must match exactly at every read; any drift fails closed with sanitized 503, and admin navigation is hidden. Pinned source bytes do NOT establish current GitHub gate status or independent authority.

## Read-only interfaces

- GET /api/v1/admin/operational-readiness — signed authorized domains only. Governance can read all three public draft summaries; each domain operator only their own. Household or supplier roles have no admin access.
- GET /api/v1/admin/operational-readiness/{domain} — exact source-linked candidate scope, pending evidence, prohibitions, draft OPEN gate number and official term-screening candidates. Rights and model training remain NOT VERIFIED for every source. Only the Finance domain can see the quoted arithmetic difference; no budget, settlement or financial command.
- GET /admin/operational-readiness/{domain} — Persian role-scoped admin page, no third user environment, no mutation form, no-store, strict form-action none CSP and escaped linked sources. Revoked sessions cannot read.

API flags legal_business_decision_authorized/decision_authorized, real_data_authorized, training_authorized and operational_actions_enabled are all false by construction. Unassigned and unknown domains return 404; corrupted files return 503. No form can upload real household or trade data and no HTTP approval operation is mounted.

## Real evidence required to advance

Domestic #2 needs actual household area/crop selection, lawful purpose-scoped consent/withdrawal/versioning, real qualified agronomy experts, reviewed scientific source rights, crop-plan AI evidence and independent producer permission and product QC before public offering. Export #3 needs a human-selected real product–destination question, exact dated/unit-bearing source version with use/republication rights, independent reviewer, and distinct export contracts before any trade. Finance #4 needs validated Sources and Uses classification, independent Domestic and per-export-contract P&L and cashflow, tax/settlement authorities, legal ownership and a real decision on the 18915 versus 7510/11405-million-toman discrepancy.

## Acceptance

Eleven new signed HTTP, isolated document tamper, explicit denial, source-rights, scoped UI, FIN-002 and immutable historic evidence tests complement the entire existing Python/Node suite. Green CI does not replace independent human review or Business/Legal/Finance permission. Business Gate Issues #2/#3/#4 remain OPEN. PRs #1/#9 Draft/Open/unmerged. No Stage, QA, Release, Production, real AI training, banking, trade or real data.
