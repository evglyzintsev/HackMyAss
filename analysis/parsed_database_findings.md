# Parsed corpus audit

Audited all 582 UTF-8 Markdown files in `Parsed/` with structural and duplicate checks; manually inspected representative prose, Arabic text, Q&A, scientific PDFs, report extracts, guideline pages, indexes, portal records, and a slide extract. Family labels in the inventory are heuristic routing candidates, not a manually verified taxonomy of every document. Originals were not edited.

## What is actually in the directory

- 144 files have ATX Markdown headings (`#` through `######`); 438 do not. Absence of headings is not evidence of missing content.
- All files use `.md`, but their internal structure differs substantially. Some are paragraph-based web prose; others retain PDF line wraps, page numbers, author affiliations, references, or fragments of slides.
- Heuristic routing: 129 research-text candidates, 71 other line-wrapped-document candidates, 33 report/chronology candidates, 14 research metadata pages, 36 guideline-site candidates, 18 Access-site listings/shells, and 281 prose/other. Categories depend on rule order and need refinement before production use.
- 231 files meet the audit's dense, short-line criterion for wrapped-document review. 219 contain at least one letter-hyphen-newline-letter sequence. These are flags, not proof that every line break or hyphen should be removed.
- 100 files contain non-whitespace control characters; 40 contain soft hyphens; two contain Unicode replacement characters (the exact duplicate pair `Dbd6e2ef149.md` and `P44.md`).

## Reliable ways to separate the content

Use a layered parser, with document-family detection before section splitting.

| Signal | Use | Important restriction |
| --- | --- | --- |
| File boundary and original filename | Stable source record and provenance | Do not infer topic, format, or priority from D/P names. No source manifest is present here. |
| ATX headings at the start of a line | Section hierarchy where present | A `##` can be a Q&A question or website heading, not the document title. `Da9b1256749.md` starts with prose before its numbered Q&A sections. Preserve that opening text. |
| Blank lines in prose | Paragraph blocks | Multiple blank lines are usually spacing, not new documents. A paragraph can contain a quote, summary, or caption. |
| Single newlines in dense extracts | Detect possible PDF/layout text | Reconstruct prose only inside plausible text runs. Preserve headings, bullets, affiliations, numeric rows, and tables. |
| Standalone Abstract / Background / Methods / Results / Discussion / References labels | Research section candidates | Require context and sequence; words inside sentences or tables of contents are not boundaries. Support bold labels and numbered variants. |
| Numbered guideline titles and lists | Topic hierarchy or index entries | Lists of medicines are often indexes; do not treat them as clinical monographs. |
| Portal field labels | Structured metadata blocks | Read values until the next recognized field; values can span several lines. |
| Repeated navigation/footer phrases | Template detection and cleaning | Repetition alone is insufficient for deletion: 'Author Contributions' and report-series names are meaningful repeated text. |

For long reports, first identify the table of contents, then real body headings; record country/chapter paths and keep references/appendices distinguishable. Do not split every all-caps line: titles and author affiliations wrap across lines too. If a parser cannot reliably reconstruct a table or slide, retain the raw span and flag it instead of inventing structure.

Examples:

- `D3889964229.md`: Arabic article, no headings, real paragraph boundaries. Preserve right-to-left text and original punctuation.
- `D014f7e7bf4.md`: research paper with a multiline title and hard line wraps. First-line-as-title and newline-as-paragraph both fail.
- `D6cbab2c6cb.md`: Spanish heading plus medicine list and Permalink chrome. Useful as an index/category record; it is not individual drug guidance.
- `D87af7060b1.md`: French guideline index containing uppercase drug names. Language menus and unavailable-language notices precede the real content.
- `D66065dc615.md`: contributors page. Filter as administrative/back matter, while retaining attribution if needed.
- `De35232409a.md`: short presentation extract, repeated photo credit, isolated chart numbers. Flag low text completeness; the parsed text alone cannot recover the visual relationships.

## What can map files to one another

1. **Raw content hash:** definitive identical-content mapping. There are four exact duplicate groups, 20 redundant copies, and 562 distinct file contents.
2. **Whitespace-normalized hash:** same duplicate groups in this corpus; normalizing whitespace did not reveal additional groups.
3. **DOI / PubMed ID:** strong research-work identity after careful extraction. A paper's References section also contains other papers' DOIs: the inventory's `doi_candidates` is intentionally not a canonical document DOI. Prefer an explicitly labelled metadata DOI or a front-matter DOI supported by the title and authors. Rejoin wrapped DOI strings only with validation and retain provenance.
4. **Title + authors + publication year:** useful fallback for matching a portal abstract to a paper. Keep abstract, full text, preprint, and final article as distinct manifestations of a shared work.
5. **Content similarity:** generate review candidates using normalized token shingles, then compare actual text. Avoid matching on shared website chrome. Translation matching requires multilingual title/entity/content comparison; this audit does not assert translation pairs.
6. **Source URL:** useful if recoverable from a manifest or original collection. URLs inside an article may be references, download links, or footnotes, so do not automatically treat the first URL as the source URL. The Parsed folder alone does not establish original URLs for every file.

Verified duplicate details:

- 18 D files, including `Dc163a8c770.md`, `Deb43f3d3b7.md`, and `Df45c9a1267.md`, contain exactly the same Access-site listing. Keep one canonical listing if needed and flag the group for possible failed article extraction. This content cannot identify 18 different underlying articles.
- Exact P/D pairs: `P16.md` ↔ `D5da0aed2fd.md`; `P42.md` ↔ `Da68d33c442.md`; `P44.md` ↔ `Dbd6e2ef149.md`.
- `P07.md` ↔ `Dd4ee6d16b7.md` has identical case-folded word-token sequences, but differs at the raw-text level.
- `P42.md` / `Da68d33c442.md` also resembles `Da384a9ee90.md` (five-token shingle Jaccard ≈ 0.893). Review differences before merging.
- The P/D comparison used a 0.40 Jaccard cutoff and retained up to three D candidates per P file. Missing matches mean no candidate under this method, not proof of unrelated content. This is not an exhaustive D-to-D similarity analysis.

## Useful filters and fields

| Field | Extraction and caveat |
| --- | --- |
| Document type | Article, interview, research abstract, full paper, report, chronology, guideline, index, contributors, slide extract, listing. Record confidence and evidence. |
| Language | Detect from cleaned substantive text. The corpus includes English, French, Spanish, and Arabic; multilingual language menus can mislead detection. The inventory counts Arabic-script characters, not document language. |
| Country / region / location | Use explicit portal Countries fields when present; otherwise named-entity extraction. Separate study/site location, operational location, author affiliation, and incidental mentions. Allow multiple locations. |
| Topic / disease / intervention / population | Portal Subject Area values offer supplied tags; otherwise inferred multi-label tags with evidence spans. Preserve supplied tags separately because they may be broad or questionable. |
| Date and date kind | Separate published, updated, study period, event date, and download date. A year in a citation or body sentence is not publication metadata. |
| Research identity | Canonical DOI, PubMed ID, title, authors, journal, volume, issue, pages. Keep candidates distinct from validated identity fields. |
| Quality / extraction status | Navigation contamination, index-only, references-only, table/slide loss, control characters, possible hyphenation, short extract, suspected truncation. Short alone does not mean unusable. |
| Duplication / relationship | Canonical content group plus relations such as duplicate, same-work abstract, translation, version, excerpt. Preserve all original filenames. |
| Section role | Main text, summary, quote, caption, references, appendix, bibliography, back matter. Helpful for retrieval filtering without discarding the source. |

`Df03791b5e1.md` demonstrates labelled Countries, Subject Area, Languages, DOI, Published Date, PubMed ID, Journal, Volume, Issue, Pages, and Issue Date. Strip Science Portal chrome and Similar Content / Loading UI, then extract title/authors/abstract/metadata. Other portal pages may vary. Preserve the original supplied metadata for traceability.

Do not globally filter by '#', file length, absence of a title, or the presence of a language-unavailability message. The latter appears in 38 files alongside real content. Do not remove all numbers, all uppercase text, or all repeated lines: this would damage dosages, results, chronology, and section labels.

## Suggested normalized representation

Use three linked tables (or equivalent JSON records):

- **documents:** original ID/path, raw hash, canonical group, family, document type, extracted title, title origin/confidence, language, publication/update dates, validated research identifiers, supplied and inferred topic/location fields, quality flags, source URL if known.
- **blocks:** document ID, block ID, block type, heading path, original character/line span, raw text, cleaned text, parsing confidence. Store cleaning offsets or a source-span mapping.
- **relationships:** source document, related document, relationship kind, evidence, similarity score, review status.

Store absent metadata as null. Distinguish a derived display label from a real title. Preserve raw text; perform NFC normalization, whitespace cleanup, navigation removal, and cautious dehyphenation in a derived layer. Do not use broad compatibility normalization or aggressive joining on clinical/numeric strings without checking the effects.

Then chunk cleaned blocks along section/paragraph boundaries, using a size limit appropriate to the target search/model. Keep short sections with their headings, split oversized sections into paragraph/sentence windows, and retain document/section provenance. Tables, lists, abstracts, and references need their own handling. The right chunk size depends on the downstream task, which was not specified here.

## Delivered audit artifacts

- `parsed_file_inventory.csv`: one row per file, structural statistics, heuristic family, quality flags, DOI candidates, hashes, and first nonempty line.
- `duplicate_groups.json`: all exact and whitespace-normalized duplicate groups.
- `P_to_D_content_candidates.csv`: content-based P-to-D matching candidates and directional shingle coverage.
- `repeated_lines.csv`: lines recurring in at least five files; review candidates, not a deletion list.
- `audit_summary.json`: aggregate counts.
- `audit_parsed.py`: reproducible structural/duplicate audit; the separate P-to-D similarity CSV records the additional comparison described above.

Recommended implementation order: canonical duplicate mapping → family routing → family-specific cleaning → metadata extraction with evidence → structural blocks → semantic tags/relations → retrieval chunks and quality filters. Preserve originals throughout.
