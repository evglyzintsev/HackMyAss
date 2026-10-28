"""Read-only corpus audit. Run from the workspace root; outputs go to analysis/."""
from pathlib import Path
import re, csv, json, hashlib, collections, statistics, unicodedata
ROOT=Path(__file__).resolve().parent.parent
out=ROOT/'analysis'
rows=[]; exact=collections.defaultdict(list); normalized=collections.defaultdict(list); repeated=collections.defaultdict(set)
for p in sorted((ROOT/'Parsed').glob('*.md')):
 t=p.read_text(encoding='utf-8'); lines=t.splitlines(); non=[x.strip() for x in lines if x.strip()]; n=len(non)
 headings=re.findall(r'^(#{1,6})\s+(.+)',t,re.M)
 blocks=[x for x in re.split(r'\n\s*\n',t) if x.strip()]
 flags=[]
 portal='Science Portal' in t and 'Subject Area' in t
 access=t.startswith('## Latest News') and 'A Snapshot of the Access Campaign' in t
 guideline='Permalink' in t and ('MSF Medical Guidelines' in t or bool(re.search(r'^# ',t,re.M)))
 doi=sorted(set(re.findall(r'10\.\d{4,9}/[^\s<>"\]]+',t)))
 doi=[x.rstrip('.,;:)') for x in doi]
 research=bool(re.search(r'(?im)^(?:RESEARCH ARTICLE|ORIGINAL ARTICLE|MAJOR ARTICLE|Accepted Manuscript|Journal Pre-proof|SYSTEMATIC REVIEW)\b',t[:6000])) or bool(doi and re.search(r'(?im)^\s*(?:abstract|background|methods|results|conclusions?)\b',t))
 short=sum(len(x)<85 for x in non)/max(n,1)
 dense=n>=50 and len(lines)/max(n,1)<1.22 and short>.65
 if portal: family='research_metadata_page'
 elif access: family='access_site_shell_or_listing'
 elif guideline: family='guideline_site_page'
 elif research: family='research_text_candidate'
 elif re.search(r'(?i)(international.{0,15}(?:activity|financial).{0,15}report|speaking out case studies|CHRONOLOGY\s+(?:OF EVENTS|\d{4}))',t[:1500]): family='report_or_chronology_candidate'
 elif dense: family='line_wrapped_document_candidate'
 else: family='prose_or_other'
 if access: flags.append('review_access_shell')
 if portal: flags.append('strip_portal_chrome_preserve_metadata')
 if guideline: flags.append('review_guideline_navigation_or_index')
 if dense: flags.append('reconstruct_wrapped_lines_before_chunking')
 if any(ord(c)<32 and c not in '\n\r\t' for c in t): flags.append('control_characters')
 if '\ufffd' in t: flags.append('replacement_character')
 if '\u00ad' in t: flags.append('soft_hyphen')
 if re.search(r'[A-Za-z]-\n[A-Za-z]',t): flags.append('line_end_hyphenation')
 if len(t)<1000: flags.append('short_extract_review')
 rawhash=hashlib.sha256(t.encode()).hexdigest(); norm=unicodedata.normalize('NFC',t); norm=re.sub(r'\s+',' ',norm).strip(); nh=hashlib.sha256(norm.encode()).hexdigest()
 exact[rawhash].append(p.name); normalized[nh].append(p.name)
 for line in set(non):
  if 20<=len(line)<=220: repeated[line].add(p.name)
 rows.append(dict(file=p.name,characters=len(t),bytes=p.stat().st_size,lines=len(lines),nonempty_lines=n,blank_line_fraction=round(1-n/max(len(lines),1),3),paragraph_blocks=len(blocks),heading_count=len(headings),heading_levels=','.join(map(str,sorted(set(len(a) for a,b in headings)))),bullet_lines=sum(bool(re.match(r'^\s*[-*+]\s+',x)) for x in lines),short_line_fraction=round(short,3),arabic_script_characters=len(re.findall(r'[\u0600-\u06ff]',t)),doi_candidates=json.dumps(doi,ensure_ascii=False),url_count=len(re.findall(r'https?://\S+',t)),family_candidate=family,flags=';'.join(flags),sha256=rawhash,whitespace_normalized_sha256=nh,first_nonempty_line=non[0][:240] if non else ''))
with (out/'parsed_file_inventory.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
dups={'exact':[v for v in exact.values() if len(v)>1],'whitespace_normalized':[v for v in normalized.values() if len(v)>1]}
(out/'duplicate_groups.json').write_text(json.dumps(dups,ensure_ascii=False,indent=2))
with (out/'repeated_lines.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['file_count','line','files'])
 for line,files in sorted(repeated.items(),key=lambda x:(-len(x[1]),x[0])):
  if len(files)>=5:w.writerow([len(files),line,';'.join(sorted(files))])
summary={'files':len(rows),'with_headings':sum(r['heading_count']>0 for r in rows),'without_headings':sum(r['heading_count']==0 for r in rows),'families_heuristic':dict(collections.Counter(r['family_candidate'] for r in rows)),'flags':dict(collections.Counter(f for r in rows for f in r['flags'].split(';') if f)),'exact_duplicate_groups':len(dups['exact']),'exact_duplicate_extra_copies':sum(len(g)-1 for g in dups['exact']),'unique_exact_contents':len(exact),'normalized_duplicate_groups':len(dups['whitespace_normalized']),'normalized_duplicate_extra_copies':sum(len(g)-1 for g in dups['whitespace_normalized']),'P_files':sum(r['file'].startswith('P') for r in rows),'P_with_exact_D_match':sum(any(f.startswith('D') for f in exact[r['sha256']]) for r in rows if r['file'].startswith('P'))}
(out/'audit_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2));print('EXAMPLE DUPLICATES',dups['exact'][:10]);print('TOP REPEATED LINES',[(len(v),k) for k,v in sorted(repeated.items(),key=lambda x:-len(x[1]))[:20]])
