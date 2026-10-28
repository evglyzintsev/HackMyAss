# Local hybrid activation

The full corpus now has a working local E5 vector index and CPU-only hybrid serving, combined with SQLite BM25 via RRF. Dependencies and the public MIT-licensed model were explicitly downloaded with user authorization; source documents and queries were not uploaded. Original Markdown filenames/content and supplied CSV are unchanged.

## Assets and reproducibility

- Model: intfloat/multilingual-e5-small, pinned revision 614241f622f53c4eeff9890bdc4f31cfecc418b3.
- Download provenance: models/download_manifest.json.
- 35,111 tokenizer-bounded windows cover all 21,951 indexed passages, normalized 384-dimensional float32 embeddings.
- Build ID, local model checksum, and complete passage-ID mapping are verified at startup.
- Batch cache allows interrupted builds to resume. CPU and local GPU were used for preprocessing; serving explicitly uses CPU.
- Tests checked cached GPU vectors against fresh CPU encodings on TB sources; differences were approximately 1e-7.
- Runtime is in .venv; use ./run_local.sh. Model/query loading is offline and telemetry disabled.

## Pagination and candidate quality

Ten is now a configurable page size (10/20/50), with Show more. Distinct result grouping precedes pagination; original filename mappings and related versions remain available. Counts describe the retrieved candidate pool, not exhaustive clinically relevant-document counts.

Keyword mode hides partial topic-word matches by default; they remain available through a checkbox. It does not pad pages: the tested detailed cholera query returned one complete-word-match source plus hidden broader candidates, rather than ten forced results. Hybrid also retains semantic candidates across wording/language differences. Vector nearest neighbors can be weak, so these are labelled candidates and are not given clinical confidence percentages.

Both lexical and dense candidate selection limit per-document concentration and demote known reference blocks before selection. This is still retrieval, not verification of clinical correctness or currency.

## Language provenance defect found during real testing

The CSV labels P22 English although it is French. Its correct vector match was being excluded by the language filter. A local audit identified eight clear narrative-language corrections; these are recorded in analysis/source_language_review.json and applied only in derived metadata, with supplied labels retained and shown. Back matter/indexes retain supplied labels because multilingual citations and medicine names make statistical language detection unreliable. Hash-bound corrections are reapplied on rebuild; changed sources invalidate stale decisions.

## Evidence

- Real-model tests cover offline loading, cross-language retrieval, normalized vectors/ID coverage, token window tails, caching, incompatible build rejection, source diversity, and path portability.
- data/hybrid_validation.json: full-production model/index loading and queries with outbound socket calls blocked, all 582 raw source hashes checked, CPU serving confirmed, and pagination beyond ten checked without repeating documents.
- English TB query with French filter returns P22 among the first three (first in the observed run). French TB query with English filter returns P21 first. PPH returns P23 first with extraction warnings preserved.
- Observed uncached CPU retrieval for those checks was roughly 70–110 ms on this machine; cold model load roughly 7 seconds. These are not target-hardware guarantees.
- data/evaluation_hybrid_comparison.json: fifteen real hybrid queries, actual retrieval mode and fallback information recorded per query. No unexpected vector fallbacks occurred.
- Hybrid is not uniformly better on the small reviewed query set: malaria research became easier to find, while some background reports still outrank focused sources. A clinician-judged independent test set is still needed before claiming precision improvements.

## Query controls and optional passage reranking

The current app includes editable condition/population/severity/task/source-preference hints from local keyword rules, plus an optional CPU-only English MS MARCO MiniLM cross-encoder. The parser is not a generative interpreter. It leaves the original request intact until an explicit edit, retains negation and unknown terms, and never silently sets language/genre filters.

The reranker considers up to three passages in eligible English documents among the first ten candidate positions. Other-language positions remain fixed. Query-language uncertainty skips this English-only model. Source review roles and missing drug identity are not overridden by genre logit bonuses. A changed passage receives fresh match metadata. Inference failures leave the hybrid order intact with a visible fallback note. These checks preserve provenance; they do not demonstrate clinical accuracy.

The reranker can be toggled per search or disabled at startup with `./run_local.sh --no-rerank`. Its download script pins revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`, and runtime loading uses only local safetensors. Model folders and derived indexes remain outside Git.
