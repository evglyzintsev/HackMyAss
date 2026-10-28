# Field Reference — offline document search

Local document retrieval for the 582 Markdown sources in `Parsed/`. Every result prominently retains the **original `.md` filename**, matching its PDF identifier. Originals and CSV metadata are never rewritten. Nothing is uploaded or pushed.

## Run now

The downloaded model and installed runtime are local to this project. Start the app with its virtual environment:

```sh
cd "/Users/evgenshlep/Documents/Artificial-Ignorance generated"
./run_local.sh
# equivalent: .venv/bin/python app.py
```

Open **http://127.0.0.1:8765**. The interface reports whether hybrid or keyword search is active and whether local English passage reranking is available. Stop with Ctrl+C. The server listens on loopback only, uses local assets, never uploads documents/queries, and does not log query strings.

To rebuild after changing sources:

```sh
.venv/bin/python build_index.py
.venv/bin/python build_vectors.py --model models/multilingual-e5-small --device cpu
./run_local.sh
```

Vector builds checkpoint each batch into a local cache and can resume. Rebuilding the text index invalidates its previous vector mapping, so rebuild vectors before restarting. Keep `Parsed/`, `data/`, and `models/` together when moving the app.

Source documents are shown as escaped original Markdown, with line numbers and matching locations highlighted. PDF paths are not configured: use the displayed exact `.md` filename to find the corresponding PDF in the original database.

## What is implemented

- CSV join by exact stem. Original genre/language labels remain preserved. A hash-bound offline language audit corrects eight clearly wrong language labels in the derived index (including French P22 labelled English in the CSV); results show supplied versus text language. Back matter/indexes retain supplied labels because cited titles and menus make automated detection unreliable. Rebuilds reapply saved language decisions; rerun `.venv/bin/python audit_languages.py` to audit changed sources. Genre is not clinical authority.
- Raw SHA-256 duplicate grouping. One indexed record retains every identical source filename and each file's CSV metadata.
- The 18 confirmed Access-site shell sources are excluded from topic search, but remain accessible through exact filename lookup.
- Conservative template cleanup and line-aware passages. Raw text and source line locations remain available. No global repeated-line deletion, translation, broad dehyphenation, or invented table reconstruction.
- A hash-bound structure review of all 70 guideline-labelled files is in `analysis/guideline_content_review.json`: 8 substantive, 22 indexes, 18 introductions/covers, 9 contributor pages, 8 glossaries, 5 bibliographies. This is not clinical validation. Missing drug identity (P24) and missing table/figure content (P23/P49) are visible in results and the source viewer. Stale reviews are ignored.
- Flags for encoding issues, short extracts, possible slides, and likely indexes/back matter. These are heuristic review flags, not clinical judgments. Some damaged extraction may be undetected.
- Five-word shingle comparisons identify possible versions/excerpts; nonidentical sources are never merged automatically. This detects textual overlap, not translations or all possible duplicate forms.
- FTS5 BM25 at passage and document level, with a conservative rank-fused document-focus signal. Candidate selection retrieves a larger pool, demotes references before selection, and caps each source at four passages to prevent long-document flooding. Title/heading/body fields use shared spelling/diacritic normalization and partial-term matching. No English-only stemming. Keyword search does not provide cross-language semantic retrieval.
- Optional offline E5 vector backend and RRF fusion. CPU-only, exact NumPy similarity, no vector service. Clinical-intent queries receive a small guideline preference; reference blocks and likely back matter are downweighted.
- Original source viewer, exact filename lookup (e.g. `P21.md`), language/genre filters, identical-file alternatives, related versions, and optional grouping of very similar versions. All filename mappings survive grouping.
- Editable condition/population/severity/task/source-preference hints from local keyword rules. Unrecognized topic words and negation are retained. The original request is used until a field is explicitly edited; edits and removals change retrieval terms, and a new request clears old edits. Source preference nudges ranking; language and genre filters are explicit. These hints are not a generative AI interpreter or clinical entity validation.
- Optional local MS MARCO MiniLM cross-encoder reranks eligible English passages within the first ten candidate positions, considering up to three passages per document. It leaves other-language positions in place and skips uncertain query languages. No genre-based bonuses are added to model logits. Passage-match labels are refreshed after selection. Reranker failures preserve the BM25/vector order and are reported. Use the UI checkbox or `./run_local.sh --no-rerank` to turn it off.
- No generated clinical answers. Evidence warnings are heuristics, not calibrated confidence or a guarantee of relevance/current guidance.

## Vector search

One-time setup, only when downloads are intended:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python build_index.py
.venv/bin/python download_model.py
.venv/bin/python build_vectors.py --model models/multilingual-e5-small --device cpu
# Optional local English reranker (~90 MB safetensors weights):
.venv/bin/python download_reranker.py
./run_local.sh
```

`download_model.py` fetches the public `intfloat/multilingual-e5-small` repository at the tested immutable revision, recorded in `models/download_manifest.json`. Only model/tokenizer/configuration files are downloaded, using safetensors weights and no remote executable model code. The model is MIT-licensed per its supplied metadata. The exact tested environment is recorded in `requirements.lock.txt`; `requirements.txt` contains the primary dependencies and a SciPy compatibility pin for this Mac.

Search and vector building then load only local files with offline/telemetry-disabled settings. E5 inputs use `query: ` and `passage: ` prefixes. A fallback opening excerpt is not repeated as a title. Long passages become overlapping tokenizer-bounded windows (256 tokens including context); every window maps back to the original passage and filename. Embeddings are normalized 384-dimensional float32 vectors. Exact NumPy dot products retrieve candidates; no vector database or hosted service is used.

`download_reranker.py` likewise pins `cross-encoder/ms-marco-MiniLM-L-6-v2` to revision `233902d25c440f23af6f7d6e94d2946bac0bee0a` and fetches safetensors plus tokenizer/configuration files. Its metadata reports Apache-2.0. Runtime loading is CPU-only, uses at most four PyTorch threads, permits no remote model code, and never downloads. The reranker is trained for English, so it is not used to replace cross-language retrieval scores. It is an optional additional relevance signal, not a verifier of medical guidance.

RRF combines lexical and semantic rankings. Non-English semantic candidates remain discoverable even without exact query-word overlap. Similarity is not a probability of relevance or clinical correctness. References and known extraction defects remain visible with suitable handling.

The local model fingerprint, text-build ID, vector matrix, and passage-ID coverage must match. A failed load/query is explicitly reported as a keyword fallback. Serving is CPU-only; preprocessing can optionally use an available local MPS device. Repeated-query embeddings are cached briefly in memory only, avoiding re-encoding for pagination.

## Result counts and pagination

Ten is an initial **page size**, not a corpus result cap. The optional reranker separately examines only the first ten candidate positions to bound CPU cost; later pages remain accessible. Choose 10/20/50 and use **Show more candidates**. Counts describe distinct documents in the ranked candidate pool, not an exhaustive count of clinically relevant documents across the corpus.

In keyword mode, incomplete topic-word matches are hidden by default; use **Include partial keyword matches** to inspect broader candidates. Results are not padded to a chosen page size. Hybrid mode also retains semantic candidates across different wording/languages and clearly labels them. Nearest-neighbor matches can still be weak; the UI does not call them confirmed clinical guidance.

## Source and index layout

```text
Parsed/                           unchanged original .md sources
D4GC Challenge 2026 Documentation.csv   supplied ID/genre/language labels
analysis/                         earlier audit and findings
local_search/                     ingestion, retrieval, optional encoder, local UI
build_index.py                    reproducible text/relationship index builder
build_vectors.py                  optional local-model vector builder
app.py                            localhost-only browser interface
evaluate.py                      timing/result report (no unjudged accuracy claims)
tests/test_search.py               integrity/retrieval tests
data/                            derived database, optional vectors, evaluation
```

Index tables: `documents` (canonical content), `sources` (every exact filename plus metadata), `passages` (section, text, raw line span), `relationships` (review candidates), `reviews` (hash-bound content inspection), passage/document FTS indexes, and `manifest`. FTS tables are contentless to avoid storing extra copies of the text; rebuild them rather than editing in place. Packaged sources beside `data/` take priority when a checkout is moved; the manifest source path is a fallback. The original file is hash-checked when opened; changing a source requires rebuilding.

## Tests and evaluation

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evaluate.py
.venv/bin/python evaluate.py --hybrid --output data/evaluation_hybrid.json
.venv/bin/python evaluate.py --hybrid --rerank --output data/evaluation_reranked.json
.venv/bin/python validate_hybrid.py
```

Optional UI-state regression checks use `node tests/test_ui.js` and require no npm packages. They check explicit field edits/removals, clearing edits on a new request, and protection against stale responses.

`data/evaluation.json` records fifteen representative queries, top results, warm retrieval times, and a source-hash check. It is a smoke benchmark, **not a clinician-validated accuracy evaluation**. No Precision@3 or success@3 is claimed without human relevance judgments. Separate reviewed-source ranks use `evaluation/retrieval_targets.json`; those only check that inspected source material is findable and are not a clinical-accuracy benchmark. An optional `--judgments /path/to/judgments.json` accepts `{ "query": ["relevant_original_filename.md"] }`. Run `--hybrid` to compare pipelines. Use `--include-partial` for comparison against the earlier broad lexical baseline; default mode mirrors the interface filtering. Use the same judgments for both.

Some requests may have only background reports or index pages in this Parsed collection. For example, matching cholera-related words does not establish that a passage is a pediatric treatment protocol. Review disease, task, population, and substantive content, not genre alone. Labels in the supplied CSV may themselves be imperfect.

Current limitations: keyword mode misses synonyms/cross-language paraphrases; the query-field parser has a finite lexicon and may misclassify words; the English reranker may skip short or ambiguous English queries and cannot establish clinical relevance; structure and quality detection are conservative heuristics; table geometry lost during extraction is not recovered; source dates/supersession are not verified; explicit action-word support is limited and semantic retrieval still requires clinical relevance evaluation; no PDF path mapping is configured. No performance claim is made for target field hardware.
