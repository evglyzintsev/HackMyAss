"""Conservative parsing. Every block retains original one-based line spans."""
import hashlib
import re
import unicodedata
from collections import Counter
from pathlib import Path

VERSION = '2'
WORD = re.compile(r'[^\W_]+', re.UNICODE)
CHROME = {
    'skip to main content', 'aller au contenu principal', 'permalink', 'sommaire',
    'select language:', 'english', 'العربية', 'español', 'français', 'anglais',
    '(arabic) العربية', 'español (spanish)', 'español (espagnol)', 'français (french)',
    'enter', 'msf.org', 'msf staff', 'personnel msf', 'google play', 'google play store',
    'app store', 'apple app store', 'or the', 'ou', '×', '.',
    '.هذه الصفحة غير متاحة باللغة العربية', 'esta página no está disponible en este idioma.',
    'cette page n’est pas disponible dans cette langue.', 'this page is not available in this language.',
    'save', 'cite', 'share', 'view html', 'loading...', 'similar content',
}
STOPWORDS = set('a an the and or of for in on to with is are how what does do from by as at about into de la le les des du pour et avec chez aux el los las para con del una un en في من مع'.split())
ALIASES = {
    'paediatric': 'pediatric', 'paediatrics': 'pediatric', 'pediatrics': 'pediatric',
    'diarrhoea': 'diarrhea', 'diarrhoeal': 'diarrheal', 'haemorrhage': 'hemorrhage',
    'haemorrhagic': 'hemorrhagic', 'anaemia': 'anemia', 'oedema': 'edema',
    'guidelines': 'guideline', 'children': 'child', 'treatments': 'treatment',
    'refugees': 'refugee', 'complications': 'complication',
}

def tokens(text):
    text = unicodedata.normalize('NFD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return [ALIASES.get(w, w) for w in WORD.findall(text)]

def normalize(text):
    return ' '.join(tokens(text))

def clean_line(line):
    # Repair known run-on abstract labels without changing original source lines.
    line=re.sub(r'^(ABSTRACT|BACKGROUND|METHODS|RESULTS|CONCLUSIONS?|Abstract|Background|Methods|Results|Conclusions?)(?=[A-Z][a-z])', r'\1 ', line)
    line = unicodedata.normalize('NFC', line).replace('\u00ad', '')
    return ''.join(c for c in line if ord(c) >= 32 or c == '\t').strip()

def shell(text):
    return text.startswith('## Latest News') and 'A Snapshot of the Access Campaign' in text and 'Get Involved!Sign up' in text

def heading(line):
    m = re.match(r'^\s*(#{1,6})\s+(.+?)\s*#*$', line)
    if m:
        return len(m[1]), m[2].strip()
    if re.fullmatch(r'\*\*[^*\n]{3,120}\*\*', line):
        title = line.strip('* ')
        if not re.match(r'(?i)(update|last update|mise à jour)', title):
            return 3, title
    if re.fullmatch(r'(?i)(abstract|background|methods|results|discussion|conclusions?|references|bibliography|références|referencias)', line):
        return 2, line
    return None

def parse(raw, filename, genre):
    raw_lines = raw.split('\n')
    is_guideline = genre == 'Clinical Guideline Chapter'
    portal = 'Science Portal' in raw[:1000] and 'Subject Area' in raw
    # Remove a known prefix, stopping before the content title after the final language notice.
    prefix_end = -1
    if is_guideline and any(x in raw[:1200] for x in ('Skip to main content', 'Aller au contenu principal')):
        for i, line in enumerate(raw_lines[:45]):
            if line.strip() == 'This page is not available in this language.':
                prefix_end = i
    if portal:
        for i, line in enumerate(raw_lines[:100]):
            if line.strip() in ('Journal Article', 'Journal article'):
                prefix_end = i - 1
                break
    retained = []
    portal_end = False
    for i, line in enumerate(raw_lines, 1):
        s = clean_line(line)
        if i - 1 <= prefix_end:
            continue
        if portal and s == 'Similar Content':
            portal_end = True
        if portal_end:
            continue
        if s.casefold() in CHROME:
            continue
        if s.startswith(('The new MSF Medical Guidelines app', 'La nouvelle application « MSF Medical Guidelines')):
            continue
        retained.append((i, s))
    substantive = [(i, s) for i, s in retained if s]
    # A label is explicitly an excerpt unless the structure supports a title.
    title = filename
    title_source = 'filename'
    first_h = next(((i, heading(s)) for i, s in substantive[:12] if heading(s)), None)
    if first_h and first_h[1][0] == 1:
        title = first_h[1][1]
        title_source = 'heading'
    elif prefix_end >= 0 and substantive:
        candidate = next((s for _,s in substantive[:12] if len(s)>15 and s not in ('Journal Article','Journal article')),substantive[0][1]) if portal else substantive[0][1]
        title = candidate[:160]
        title_source = 'extracted_label'
    elif substantive:
        s = re.sub(r'^[#*\s]+|[*\s]+$', '', substantive[0][1])
        title = s[:140] + ('…' if len(s) > 140 else '')
        title_source = 'opening_excerpt'
    quality = []
    if any(ord(c) < 32 and c not in '\n\r\t' for c in raw):
        quality.append('control_characters_in_source')
    if '\ufffd' in raw:
        quality.append('encoding_damage_in_source')
    if len(raw.strip()) < 1000:
        quality.append('short_extract_review')
    if re.search(r'(?i)\b(presented by|keynote speech)\b', raw[:1500]):
        quality.append('possible_slide_layout')
    role = 'content'
    lower = title.casefold()
    if is_guideline:
        if any(x in lower for x in ('contribut', 'auteur', 'acknowledg', 'abbreviat', 'abréviation', 'bibliograph', 'sites consultés')):
            role = 'back_matter'
        elif any(x in lower for x in ('medicamentos de uso', 'médicaments à usage', 'medicines for external', 'médicaments potentiellement', 'appendices', 'annexes')):
            role = 'index_or_front_matter'
        elif len(substantive) < 45 and sum(bool(re.match(r'^(?:[-*]\s|\d+\.\d+\s)', s)) for _, s in substantive) / max(1,len(substantive)) >= .65 and sum(len(s) > 220 for _,s in substantive) < 2:
            role = 'index_or_front_matter'
        elif 'please note that the pdf below' in raw.casefold():
            role = 'index_or_front_matter'
    table_rows = [s for _,s in substantive if s.startswith('|') and s.count('|')>=3]
    acronym_rows = [s for s in table_rows if re.match(r'^\|\s*[A-Z][A-Za-z0-9/+-]{0,9}\s*\|\s*[A-Za-z]',s)]
    if is_guideline and len(acronym_rows)>=12 and len(acronym_rows)/max(1,len(table_rows))>.7:
        role='back_matter'
    if role != 'content':
        quality.append(role)
    if shell(raw):
        quality.append('confirmed_repeated_site_shell')
    # Line-aware blocks: blank lines/headings/lists/tables remain boundaries.
    blocks = []
    stack = []
    current = []
    current_role = 'body'
    def flush():
        nonlocal current
        if current:
            blocks.append({'text': '\n'.join(s for _, s in current), 'line_start': current[0][0],
                           'line_end': current[-1][0], 'section': ' › '.join(t for _, t in stack),
                           'role': current_role, 'source_lines': [i for i,_ in current]})
            current = []
    for i, s in retained:
        h = heading(s)
        if h:
            flush()
            level, label = h
            stack = [(lev, txt) for lev, txt in stack if lev < level] + [(level, label)]
            current_role = 'references' if re.fullmatch(r'(?i)(references|bibliography|références|referencias)', label) else 'body'
            current = [(i, s)]
            continue
        if not s:
            flush()
            continue
        if current and (s.startswith(('|', '- ', '* ')) or current[-1][1].startswith('|')):
            # Keep adjacent table rows/list items together within the same block.
            if not (s.startswith('|') and current[-1][1].startswith('|')) and not (s.startswith(('- ', '* ')) and current[-1][1].startswith(('- ', '* '))):
                flush()
        current.append((i, s))
    flush()
    # Confident terminal numbered citation runs, including unheaded bibliographies.
    # Require multiple numbered entries and URLs; don't truncate or delete later appendices.
    citation_mode=False
    citation_section=None
    for j,b in enumerate(blocks):
        if citation_mode and b['section']!=citation_section:
            citation_mode=False
        lookahead='\n'.join(x['text'] for x in blocks[j:j+8])
        first=re.match(r'^\s*(?:[-*]\s*)?1[.)]\s*\S',b['text'])
        multi_citation=len(re.findall(r'https?://',lookahead))>=2 and re.search(r'(?m)^\s*(?:[-*]\s*)?2[.)]\s*\S',lookahead)
        single_citation=j>=len(blocks)-3 and re.search(r'(?i)(World Health Organization|\bet al[.]|\bdoi:|\bISBN)',lookahead) and 'http' in lookahead
        if first and b['line_start']>len(raw_lines)*.5 and (multi_citation or single_citation):
            citation_mode=True
            citation_section=b['section']
        if citation_mode:
            b['role']='references'
        if re.match(r'^\s*(?:[-*]\s*)?(?:\([a-z]\))?For more information on',b['text']) and 'http' in b['text']:
            b['role']='references'
    return {'title': title, 'title_source': title_source, 'quality': quality, 'content_role': role, 'blocks': blocks}


def passages(blocks, max_words=180):
    """Bounded search units, preserving exact raw line spans for the viewer."""
    out = []
    pending = []
    count = 0
    def emit():
        nonlocal pending, count
        if pending:
            text = '\n\n'.join(b['text'] for b in pending)
            if len(tokens(text)) >= 4:
                out.append({'text': text, 'section': pending[0]['section'], 'role': pending[0]['role'],
                            'line_start': pending[0]['line_start'], 'line_end': pending[-1]['line_end']})
            pending, count = [], 0
    for block in blocks:
        words = list(re.finditer(r'\S+', block['text']))
        if not words:
            continue
        if pending and (block['section'] != pending[-1]['section'] or block['role'] != pending[-1]['role'] or count + len(words) > max_words):
            emit()
        if len(words) > max_words:
            emit()
            for j in range(0, len(words), max_words - 35):
                start = words[j].start()
                end = words[min(j + max_words, len(words)) - 1].end()
                out.append(dict(block, text=block['text'][start:end],
                                line_start=block['source_lines'][block['text'][:start].count('\n')],
                                line_end=block['source_lines'][block['text'][:end].count('\n')]))
                if j + max_words >= len(words):
                    break
        else:
            pending.append(block)
            count += len(words)
    emit()
    return out


def shingles(text):
    ws = tokens(text)
    return {hashlib.blake2b(' '.join(ws[i:i+5]).encode(), digest_size=8).digest() for i in range(len(ws)-4)}
