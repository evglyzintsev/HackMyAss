# Offline clinical document search: implementation handoff

> Earlier planning brief retained for corpus context. The current implementation (including later optional passage reranking) and run commands are documented in [README.md](README.md).

## Goal and deadline

Build a working offline document search prototype for doctors in crisis zones. Budget: approximately three hours. Example query: "Cholera treatment guidelines for children with severe dehydration". Return relevant source passages and let users open the source document. Do not generate medical answers.

Preferred architecture: BM25 + multilingual dense retrieval, merged with reciprocal rank fusion (RRF). Keep BM25 working if model setup fails. No cross-encoder, knowledge graph, topic modeling, training, hosted APIs, or elaborate automatic classification in this iteration.

## Get the real corpus first

Repository: https://github.com/evglyzintsev/HackMyAss

The repository contains `Parsed/` and `analysis/`. Clone it or work directly in its checkout. The Markdown files are the database; there is no database service to connect. A format description cannot replace these files for relevance evaluation.

Before editing, inspect any repository instructions and existing implementation. Preserve original documents. This handoff describes the audited corpus, not necessarily future changes to the repository.

If corpus access is unavailable, build interfaces and clearly labelled synthetic test fixtures only. Do not claim real-corpus counts, relevance, latency, or successful offline packaging without testing them. Do not assume the example query is answerable from this collection.

## Verified corpus facts

- 582 files, all `.md`.
- 144 have ATX Markdown headings (`#` through `######`); 438 do not.
- English, French, Spanish, and Arabic occur. Exact language counts are unknown.
- 39 filenames begin with P; other filenames use opaque D identifiers. Their semantic meaning is unknown. Retain filenames as source IDs.
- 562 distinct raw file contents: four exact duplicate groups, 20 extra copies.
- 18 differently named files contain the same Access-site listing text. They do not establish 18 distinct articles. Exclude this known group from default substantive search; preserve source files.
- 231 files meet a heuristic dense/short-line criterion; 219 contain letter-hyphen-newline-letter sequences. These are review flags, not blanket permission to join all lines or delete all hyphens.
- 100 files contain non-whitespace control characters; 40 contain soft hyphens; two contain replacement characters.
- Family classifications in the audit are heuristics, not verified document types.

Detailed evidence:

- `analysis/parsed_database_findings.md`
- `analysis/parsed_file_inventory.csv` — one row per source, statistics, family candidates, flags, hashes.
- `analysis/duplicate_groups.json` — verified duplicate group membership.
- `analysis/repeated_lines.csv` — repeated-line candidates, NOT a deletion list.
- `analysis/P_to_D_content_candidates.csv` — limited similarity candidates, NOT exhaustive duplicate mapping.
- `analysis/audit_parsed.py` — reproducible structural audit.

## Formats and examples

### 1. Web prose without headings

Example: `Parsed/D3889964229.md`, Arabic article.

Paragraphs separated by blank lines. First line may be a full paragraph, not a title. Preserve Unicode and paragraph boundaries. Do not infer Arabic document language merely because Arabic appears in a website menu.

### 2. Prose with Markdown headings / interviews

Example: `Parsed/Da9b1256749.md`.

Starts with introductory paragraphs, followed by `## 1. What is the situation in north Gaza?` and other questions. Keep introductory text. Heading denotes a section, not necessarily the document title.

### 3. PDF-derived research text

Examples: `Parsed/D014f7e7bf4.md`, `Parsed/D5da0aed2fd.md`.

Multiline titles, authors/affiliations, hard line wrapping, page numbers, headers, abstract/body sections, references. Single newlines often do not indicate paragraphs. Some words break across lines. Tables may have lost their geometry.

Do not flatten the full document into a single string before identifying blocks. Do not globally remove uppercase lines, numeric lines, or unit strings. Keep potentially damaged tables readable in the source viewer; do not claim to reconstruct their meaning.

### 4. Research portal metadata pages

Example: `Parsed/Df03791b5e1.md`.

Starts with Science Portal/navigation/footer text. Then article type, title, authors on separate lines, Abstract, and labelled metadata including Countries, Subject Area, Languages, DOI, Published Date, PubMed ID, Journal, Volume, Issue, Pages, Issue Date. Labels/values are commonly on separate lines, not `Title: value`.

Strip only recognized chrome. Preserve abstract and metadata. A DOI elsewhere in References is not necessarily the source document DOI.

### 5. Guideline-site pages and indexes

Examples:

- `Parsed/D6cbab2c6cb.md`: Spanish heading plus a list of external medicines and antiseptics; an INDEX, not individual drug instructions.
- `Parsed/D87af7060b1.md`: French medicine index, with long app/language navigation before the content.
- `Parsed/D66065dc615.md`: contributors page, administrative/back matter.
- `Parsed/D49a9834c4f.md`: guide introduction beginning with a bold update date.

The audit's 36 guideline-site candidates are NOT 36 verified clinical guidelines. Avoid automatic authority badges or strict filters based on that label.

### 6. Long reports and historical case studies

Examples: `Parsed/D32ea4a9d92.md`, `Parsed/D99b084ca58.md`.

Long documents containing front matter, contents, chapters, dates, countries, appendices, and repeating page furniture. A single global document embedding is unsuitable for precise passage retrieval. Preserve source location and parent context.

### 7. Presentation extracts

Example: `Parsed/De35232409a.md`.

Short fragments, photo credits, disconnected chart values. Flag layout uncertainty. Avoid fabricated narrative or table reconstruction.

### 8. Known repeated listing/shell

Example: `Parsed/Dc163a8c770.md`.

Begins `## Latest News`, includes `A Snapshot of the Access Campaign`, repeated sign-up prompts and photo credits. Use the known duplicate-group identity or a specific signature; do not label every group of >=5 duplicates a shell.

## Cleaning rules

1. Keep raw text and file IDs unchanged on disk.
2. Raw SHA-256 deduplication is safe for canonical content grouping. Preserve all associated filenames. Treat token-normalized similarity as a candidate relationship, not definitive clinical equivalence.
3. Preserve Unicode; use NFC in derived search text if needed.
4. Remove recognized navigation/templates conservatively. Never delete every line occurring in N documents: meaningful headings recur too.
5. Keep bibliography separate or downweight it when confidently identified. Avoid broad truncation on the first occurrence of References; reports can contain contents entries and later appendices.
6. Dehyphenation is optional and conservative. Keep a raw viewer and record that search text was cleaned.
7. A fallback display label is not a verified title. Store `title_source`/confidence. Use an opening excerpt or filename when uncertain; do not invent titles.
8. Missing metadata stays unknown. Inferred metadata should not silently exclude results.

## Minimal data model

Documents:

- `doc_id`, `source_files[]`, `raw_hash`
- `display_title`, `title_source`
- `raw_text`, optional `cleaned_text`
- optional `language`, `document_type`, confidence/quality flags

Passages:

- `passage_id`, `doc_id`
- `section_path`, `text`
- source span (prefer line/character offsets into raw text)
- source context for opening the relevant location

Use SQLite for records and FTS5. Store float32 passage embeddings in an array plus an explicit ordered passage-ID mapping. Store model identifier/revision and preprocessing version in a build manifest. Validate that embeddings, IDs, and index belong to the same build.

## Retrieval implementation

### Lexical

Use SQLite FTS5 BM25, with title/section/body fields. Escape query syntax and parameterize SQL. Natural-language input should not become an accidental strict AND query: use deliberate token/phrase handling and partial-match fallback. SQLite BM25 ranks better matches with lower scores.

Use one shared normalization path for query and corpus. Any synonyms must be tokenized consistently; a multiword phrase cannot be treated as one token against a word-token index. Keep the alias dictionary small and reviewed. Do not treat children, infants, and neonates as equivalent, or equate severe dehydration with all rehydration interventions.

### Semantic

Pick a small multilingual model with suitable license and locally available runtime. Timebox model setup to ~20 minutes. Download/save the model centrally and load it by local path with network access disabled at deployment.

Chunk using the actual model tokenizer, reserving token capacity for title/heading. Do not assume 160 words fit a 128-token model. Prefer section/paragraph boundaries; split oversized blocks and keep bounded surrounding source context.

Compute normalized passage embeddings at build time. At runtime encode the query with the identical model and preprocessing, then use exact NumPy dot products. Benchmark before adding an ANN database. Local query encoding still consumes CPU even though document embeddings were precomputed.

### Fusion

Starting experiment: top 50 lexical passages and top 50 dense passages, RRF constant 60. These are tunable defaults, not measured optima.

`score(p) = sum(1 / (60 + rank(p)))`, ranks start at 1.

A retriever contributes only if it returned the passage. Never add raw BM25 and cosine scores directly. Do not populate lexical results with zero-evidence candidates.

Group passage results by document after fusion, retaining the best passage and optionally a second useful passage. Return around 10 documents. Display matching evidence, source IDs, and quality uncertainty. Similarity or concept coverage is not a clinical confidence percentage.

Only apply modest type boosts from checked labels. No keyword-count-based "clinical authority" multiplier. User-selected filters can be strict; automatically inferred facets should usually be soft.

### Weak matches

Always exposing ten results as authoritative is misleading. Provide a clear weak-match state based on observed evidence and validation. If no defensible threshold is established, show results as unverified matches rather than fabricating a confidence measure. Include no-answer queries in tests.

## UI

Streamlit is acceptable for a prototype.

- Query box, search button, readable results.
- Each result: display title, best source passage, filenames, optional checked type/language.
- Open the complete original document with formatting/line breaks intact and locate the matching section where possible.
- BM25-only mode works if the semantic model is unavailable; show active mode.
- Optional lexical/hybrid comparison toggle for evaluation.
- No generated medical advice, misleading authority badges, or unsupported benchmark claims.

## Three-hour priorities

0–20 min: inspect files and existing code; initialize project; confirm FTS5; download/test a small model. If model setup is blocked, continue lexical-first.

20–65 min: implement conservative ingestion, verified deduplication/shell exclusion, passage records, FTS5, dense index if model ready.

65–105 min: search/fusion, document grouping, source viewer, clear errors/fallback.

105–150 min: benchmark 10–15 varied realistic queries, inspect failures, correct parsing and ranking problems. Verify the relevant content actually exists. Do not tune only to cholera.

150–180 min: freeze features, test networking-disabled startup/search/viewing, measure runtime and package size, write exact run instructions.

Defer rerankers, graphs, LDA/NMF, training, sophisticated NER, generated questions, automatic translation, and elaborate metadata extraction.

## Validation and acceptance

- All sources accounted for: indexed, duplicate-mapped, or excluded with reason.
- Known duplicate documents do not flood results.
- Known Access listing group excluded from default substantive results.
- Non-Latin text survives ingestion and display.
- Section headings/lists remain readable; displayed source matches retrieved content.
- Passage IDs and embedding rows align after rebuild.
- Empty, punctuation-only, unknown-term, and no-answer queries are handled.
- BM25 baseline and hybrid evaluated on the same judged queries.
- Judge disease, task, population, and actual usefulness; "is a guideline" alone is not relevance.
- Record Precision@3 or success@3, candidate recall where judgments permit, and misleading matches separately.
- Measure warm-query latency and cold-start latency separately, plus RAM/disk size. No promised 5/15/100 ms figures without measurements on specified hardware.
- Successful fully offline run with the bundled model and dependencies.

## Deliverables

Implementation, dependency/version instructions, reproducible build command, local run command, model packaging notes, small evaluation table with actual judgments/timings, and explicit limitations. Preserve corpus and audit artifacts. Do not push changes unless the human requests it.
