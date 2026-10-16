# Ronas Export research finding drafts

The shared management Export workspace now accepts append-only analyst-note
drafts at `POST /api/v1/admin/export/research/drafts/{ref}/findings` and
`POST /admin/export/research/drafts/{ref}/findings`. A finding is bound to the
exact current case version, research-question revision, and one evidence
reference recorded for that question. The browser form uses the current
evidence references only; the ledger independently verifies the same binding.

Each note is limited to 2,000 characters and must begin `DEMO:` in this
LOCAL/TEST contract. Replays with identical commands return the original
revision; conflicting replays and stale question/evidence/finding revisions
return a conflict. Revisions are immutable, SHA-256 linked, and paired with an
audit event in the same SQLite transaction. Integrity verification checks the
whole finding chain and its question/evidence references before serving the
Export workspace.

The UI tracks question and evidence lineage independently. A note is marked
`HISTORICAL` for evidence when a newer evidence-reference revision is recorded
for the same question, even if the question itself remains current. Creating a
new question does not rewrite or carry forward old notes. Findings are notes only: the contract
does not establish source rights, market truth, HS classification, report
approval, buyer verification, pricing, contract, or commercial actions. All
such approval flags remain false.

Validation: `backend/tests/test_export_research_queue.py` covers append/replay,
conflict handling, stale source and question rejection, immutable lineage,
historical question and evidence projection, browser CSRF/Origin handling, and
workspace rendering.
