# Bugs to investigate

Oddities seen during a build or a release that were not root-caused at the time. One entry
each: what was seen, where, what it might be, how to check, and what it blocks. Metadata only
(no query, chunk text, key or raw id). Strike an entry when it is explained or fixed, with
the item that did so.

## B-1 RAGFlow chunk count and chunk listing disagree (P2A-00 probe, Oct 25, 2026)

**Seen.** On the Phase 1c Instance, RAGFlow `v0.27.2`, the largest `sample-reports` PDF
reports `chunk_count` 1128 on the document record, while the paged chunk list
(`GET /api/v1/datasets/<dataset_id>/documents/<document_id>/chunks`) returns 1079 chunks.
The same figures before and after the probe's five pause/resume cycles, so the probe did not
cause it. Other documents were not compared.

**Possible causes, in the order to check.**
1. The listing excludes chunk kinds the counter includes: knowledge-compilation chunks
   (`compile_kwd`), which the `enabled` toggle also skips and our retrieval excludes
   (`include_knowledge_compilation: false`), or table and image chunks stored under another
   type. If so, the 49 are invisible to our retrieval by design and the gap is cosmetic.
2. The counter is incremented at parse for chunks the doc store later rejected or
   de-duplicated (49 chunks never indexed). Then 49 passages of that document are not
   retrievable and the document should be re-parsed.
3. A paging or `total` fault in the listing endpoint (chunks exist and are retrievable, the
   list under-reports).

**How to check** (on the Instance, from the `api` container, `sample-*` datasets only, no
text printed): count documents in the index for the document id directly, with and without
`compile_kwd`, and compare with the listing's `total` and the record's `chunk_count`; repeat
for two or three other `sample-reports` documents to see whether the gap is general. If cause 2,
record the affected documents and re-parse them through the register's retry path, then
compare again. About an hour.

**Blocks.** Nothing in Phase 2A. P2A-01 verifies a pause by the returned `data.status`, not by
the chunk list. If cause 2 holds for other documents too, it is a retrieval-quality issue for
the content team and belongs in the Phase 2A findings and the corpus checklist.
