# Local retrieval quality review

This records the earlier lexical review. Current implementation and validation are documented in `../README.md`, `hybrid_activation.md`, and `implementation_validation.md`.

This is a source-content and software review, not a clinical validation. Original Markdown files, identifiers, and supplied CSV were left unchanged. No models or packages were downloaded and nothing was uploaded or pushed.

## What the collection actually supports

All 70 files labelled Clinical Guideline Chapter in the CSV were inspected. Eight contain substantive text/tables: five disease/drug/table sources plus three general prescribing-convention pages. The other 62 are indexes (22), introductions/covers (18), contributors (9), glossaries (8), or bibliographies (5). The hash-bound decisions, evidence spans, and warnings are in `guideline_content_review.json`.

- P21: pulmonary TB, including a Treatment section.
- P22: French pulmonary TB treatment counterpart.
- P23: postpartum hemorrhage management, but tables and figures are incompletely extracted. Warnings accompany the result and source viewer.
- P24: substantive drug monograph with no medicine name present in the extract. It is explicitly marked `missing_drug_identity`. No drug identity was inferred.
- P49: TB regimen/eligibility table with layout damage/continuation caveat.

No substantive matching cholera-child-severe-dehydration protocol was found among the reviewed guideline-labelled sources; apparent guideline hits are cover/appendix-index pages. Reviewed measles guideline pages likewise contain introductions/indexes rather than the requested complications protocol. These are scoped findings about the reviewed subset, not proof that every medical detail is absent from every paper/report or from the original PDFs.

## Fixes made

1. Candidate selection retrieves a larger passage pool, downweights references BEFORE selection, and caps each source at four candidate passages. This prevents a few long reports and bibliographies from consuming the whole pool.
2. A small whole-document BM25 rank contribution helps focused source documents. Passage and document ranks are fused; raw scores from different indexes are not directly added.
3. Unverified opening excerpts no longer get repeated as document-title evidence in every passage.
4. Reviewed content roles override the misleading assumption that a guideline-site index is substantive guidance. Stale source reviews are rejected by hash. Supplied CSV genre labels remain unchanged and visible.
5. Headingless numbered bibliography runs and clear reference-only footnotes are tagged without deleting them or demoting unrelated clinical footnotes. References, lists, appendices, and raw source remain accessible.
6. Shared normalization handles a few spelling/plural variants; glued abstract labels such as ABSTRACTPregnancy are separated in derived text. No medical translation or broad clinical-equivalence dictionary was introduced.
7. A bounded proximity signal and task-heading preference improve matching; missing query words are shown for partial matches. These heuristics do not establish clinical relevance.
8. Python parsing and the browser now share LF-based source line numbering, fixing control-character highlight drift. Source hashes are verified on opening.
9. Moving a package uses its packaged Parsed sources before the old build-machine source path.
10. Results expose other matching sections and optional related versions. All original filename mappings survive exact/near-duplicate handling.
11. Contentless FTS tables avoid extra stored text copies. Current index is about 51.7 MiB; originals are separate.

## Evaluation evidence and limits

`data/evaluation_before_review.json` preserves the earlier smoke output. `data/evaluation.json` records 15 current queries and source hashes; `data/retrieval_comparison.json` records comparable before/after top-three filenames. Reviewed retrieval targets are in `evaluation/retrieval_targets.json`.

Observed changes:

- Pulmonary TB: P21's Treatment passage remains first; P49's regimen table moves into second place.
- AMR surveillance: the inspected Mini-Lab/surveillance source D8ad70d7749 appears third, previously outside the top three.
- Relevant malaria-in-pregnancy research abstract Dea6c3f0f10 is retrievable within ten after repairing its glued abstract label; it is not presented as a protocol.
- Direct refugee mental-health narrative D802e76ecc1 is retrievable within ten; generic report matches still rank ahead of it.
- Cholera and measles clinical requests explicitly show the limited-guidance state. Background reports remain discoverable rather than being falsely declared absent.
- Exact P24 lookup displays the missing-drug-identity warning; P23 displays extraction warnings.

At that lexical review stage, twenty-nine automated tests passed, including candidate starvation, reference footnotes, raw line locations/control characters, moved packages, stale review hashes, partial/unknown queries, vector-error fallback, duplicate mappings, and source preservation. Additional real-corpus checks verified all 582 source hashes and source-viewer line counts, known TB/PPH matches, gap warnings, and excluded-shell filename access.

The 15-query run measured median warm retrieval around 19 ms on this machine. This excludes server/model startup and is not a performance claim for weak field hardware. No clinical Precision@3 or success@3 is reported without human relevance judgments. The inspected target list is small and selected, not an unbiased benchmark. Some broad reports still outrank more focused narratives.

## Remaining work

- Completed subsequently: local E5 runtime/model, full-corpus vectors, editable query hints, and optional English passage reranking. See `hybrid_activation.md` and `implementation_validation.md`.
- Ask clinicians to judge disease, task, population, completeness, and currency on a larger independent query set.
- Configure the actual PDF directory/database links. Original .md IDs already remain the stable mapping.
- Recover missing tables, images, and drug identity from original PDFs upstream. Search cannot safely reconstruct absent content.
