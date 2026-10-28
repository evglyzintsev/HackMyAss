import contextlib
import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_index import build, SCHEMA
from local_search.ingest import parse, passages, normalize
from local_search.search import connect, document, rrf, search, minimum_span
from local_search.lexical import retrieve


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        (cls.root/'Parsed').mkdir()
        docs={
            'P01.md':('# Cholera manual\n\n## Children\n\nCholera treatment for children with severe dehydration.\n\nA list stays in context:\n- First entry\n- Second entry\n', 'Clinical Guideline Chapter','en'),
            'Dcopy.md':('# Cholera manual\n\n## Children\n\nCholera treatment for children with severe dehydration.\n\nA list stays in context:\n- First entry\n- Second entry\n', 'Clinical Guideline Chapter','en'),
            'Dar.md':('## الرعاية\n\nهذه وثيقة عن الكوليرا والرعاية الطبية للأطفال.\n', 'Project Update','ar'),
            'Dresearch.md':('# Research\n\nCholera epidemiology study and disease surveillance.\n\n## References\n\nA cited cholera treatment paper.\n\n## Appendix\n\nAdditional cholera results.\n','Peer-reviewed Article','en'),
            'Dshell.md':('## Latest News\n\nA Snapshot of the Access Campaign\n\nGet Involved!Sign up to stay updated.\n','Statement','en'),
            'Dvariant.md':('# Cholera manual\n\nCholera treatment for adults; guidance differs.\n','Clinical Guideline Chapter','en'),
            'Dfront.md':('# Contributors\n\nNames for the cholera manual.\n','Clinical Guideline Chapter','en'),
        }
        base=' '.join(f'word{i}' for i in range(400))
        docs['Dlong.md']=('# Long source\n\n'+base+' original ending', 'Report','en')
        docs['Dversion.md']=('# Long source\n\n'+base+' different ending', 'Report','en')
        docs['Dexcerpt.md']=(' '.join(f'word{i}' for i in range(100,300)), 'Report','en')
        with (cls.root/'D4GC Challenge 2026 Documentation.csv').open('w',newline='') as f:
            w=csv.writer(f);w.writerow(['id','genre','language'])
            for name,(text,genre,language) in docs.items():
                (cls.root/'Parsed'/name).write_text(text)
                w.writerow([Path(name).stem,genre,language])
        cls.before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (cls.root/'Parsed').iterdir()}
        cls.db=cls.root/'data/search.sqlite'
        with contextlib.redirect_stdout(io.StringIO()):
            build(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_original_files_unchanged(self):
        after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root/'Parsed').iterdir()}
        self.assertEqual(self.before,after)

    def test_exact_duplicate_all_identifiers_retained(self):
        c=connect(self.db)
        a=c.execute("SELECT doc_id FROM sources WHERE filename='P01.md'").fetchone()[0]
        b=c.execute("SELECT doc_id FROM sources WHERE filename='Dcopy.md'").fetchone()[0]
        self.assertEqual(a,b)
        self.assertEqual(c.execute('SELECT count(*) FROM sources').fetchone()[0],10)
        c.close()

    def test_exact_lookup_uses_requested_alias(self):
        r=search(self.db,'P01.md')['results'][0]
        self.assertEqual(r['filename'],'P01.md')
        self.assertEqual({s['filename'] for s in r['sources']},{'P01.md','Dcopy.md'})

    def test_topic_search_no_duplicate_flood(self):
        r=search(self.db,'cholera treatment children severe dehydration')['results']
        self.assertEqual(len({x['doc_id'] for x in r}),len(r))
        self.assertEqual({s['filename'] for s in r[0]['sources']},{'P01.md','Dcopy.md'})

    def test_shell_excluded_but_exact_filename_accessible(self):
        self.assertFalse(search(self.db,'Snapshot Campaign')['results'])
        r=search(self.db,'Dshell.md')['results'][0]
        self.assertEqual(r['excluded_reason'],'confirmed_repeated_site_shell')
        self.assertIsNone(r['passage'])

    def test_language_and_genre_filters(self):
        r=search(self.db,'cholera',genre='Peer-reviewed Article')['results']
        self.assertTrue(r)
        self.assertTrue(all(x['genre']=='Peer-reviewed Article' for x in r))
        self.assertFalse(search(self.db,'cholera',language='ar')['results'])
        self.assertEqual(search(self.db,'الكوليرا',language='ar')['results'][0]['filename'],'Dar.md')

    def test_raw_document_and_line_span(self):
        r=search(self.db,'cholera treatment children')['results'][0]
        d=document(self.db,r['filename'])
        self.assertEqual(d['text'],(self.root/'Parsed'/r['filename']).read_text())
        p=r['passage'];original='\n'.join(d['text'].splitlines()[p['line_start']-1:p['line_end']])
        self.assertIn('Cholera',original)

    def test_unsafe_file_paths_rejected(self):
        with self.assertRaises(KeyError):
            document(self.db,'../../README.md')

    def test_empty_unknown_and_punctuation(self):
        for q in ('','???','xyzdoesnotexist'):
            self.assertEqual(search(self.db,q)['results'],[])
        search(self.db,'" OR * : ( NOT )')  # Valid parameterized FTS query, no syntax exception.

    def test_shared_heading_preserved(self):
        p=parse('# Title\n\nAuthor Contributions\n\nAuthor list.','x.md','Peer-reviewed Article')
        self.assertIn('Author Contributions','\n'.join(b['text'] for b in p['blocks']))

    def test_references_do_not_cut_appendix(self):
        raw='# Title\n\nMain.\n\n## References\n\nCited item.\n\n## Appendix\n\nUseful appendix.'
        b=parse(raw,'x.md','Peer-reviewed Article')['blocks']
        self.assertEqual(next(x for x in b if 'Useful appendix' in x['text'])['role'],'body')
        self.assertEqual(next(x for x in b if 'Cited item' in x['text'])['role'],'references')

    def test_list_not_mistaken_for_empty_index(self):
        text='\n\n'.join(['Clinical description. '*30]+['- Clinical detail. '*25 for _ in range(5)])
        self.assertEqual(parse(text,'x.md','Clinical Guideline Chapter')['content_role'],'content')

    def test_line_spans_survive_chrome_removal(self):
        raw=' '.join(['alpha']*150)+'\nPermalink\n'+' '.join(['beta']*150)+'\n'
        p=parse(raw,'x.md','Report')
        chunks=passages(p['blocks'],max_words=100)
        self.assertTrue(any(x['line_start']==3 for x in chunks))
        self.assertTrue(all(1<=x['line_start']<=x['line_end']<=3 for x in chunks))

    def test_rrf_absent_retriever_contributes_nothing(self):
        s=rrf([[1,2],[2,3]])
        self.assertAlmostEqual(s[1],1/61)
        self.assertGreater(s[2],s[1])

    def test_hybrid_interface_with_fake_encoder(self):
        c=connect(self.db)
        pid=c.execute("SELECT id FROM passages WHERE doc_id='Dar.md' LIMIT 1").fetchone()[0]
        c.close()
        class Fake:
            def search(self,query,limit,allowed):
                return [pid] if allowed is None or pid in allowed else []
        r=search(self.db,'xyznotlexical',dense=Fake())
        self.assertEqual(r['mode'],'hybrid')
        self.assertEqual(r['results'][0]['filename'],'Dar.md')
        self.assertEqual(r['evidence'],'limited')
        self.assertFalse(search(self.db,'xyznotlexical',dense=Fake(),mode='keyword')['results'])
        self.assertFalse(search(self.db,'xyznotlexical',dense=Fake(),language='en')['results'])

    def test_near_versions_and_excerpts_remain_separate(self):
        c=connect(self.db)
        rows=c.execute('SELECT * FROM relationships').fetchall()
        self.assertTrue(any(r['kind']=='possible_version' for r in rows))
        self.assertTrue(any(r['kind']=='possible_excerpt' for r in rows))
        self.assertEqual(c.execute("SELECT count(DISTINCT doc_id) FROM sources WHERE filename IN ('Dlong.md','Dversion.md','Dexcerpt.md')").fetchone()[0],3)
        c.close()

    def test_wrong_condition_guideline_does_not_clear_warning(self):
        r=search(self.db,'treatment unknownconditionzz severe')
        self.assertEqual(r['evidence'],'limited')

    def test_vector_error_keeps_keyword_search_working(self):
        class Broken:
            def search(self,*args):
                raise RuntimeError('Model failure')
        r=search(self.db,'cholera',dense=Broken())
        self.assertEqual(r['mode'],'keyword')
        self.assertTrue(r['results'])
        self.assertIn('vector search failed',r['message'])

    def test_controls_do_not_shift_raw_line_numbers(self):
        raw="alpha\vbeta\fgamma\n\n## Treatment\nActual body text here.\n"
        parsed=parse(raw,'controls.md','Report')
        chunks=passages(parsed['blocks'])
        self.assertEqual(next(x for x in chunks if 'Actual body' in x['text'])['line_start'],3)
        self.assertEqual(next(x for x in chunks if 'Actual body' in x['text'])['line_end'],4)

    def test_unheaded_bibliography_is_kept_but_tagged(self):
        raw='\n\n'.join(['Main body paragraph.']*8)+"\n\n- 1.World Health Organization. Report 2020.\nhttps://example.invalid/one\n\n- 2.World Health Organization. Report 2021.\nhttps://example.invalid/two\n"
        b=parse(raw,'refs.md','Peer-reviewed Article')['blocks']
        self.assertTrue(any(x['role']=='references' and 'example.invalid' in x['text'] for x in b))
        self.assertTrue(any(x['role']=='body' and 'Main body' in x['text'] for x in b))

    def test_reference_footnote_does_not_demote_clinical_footnotes(self):
        raw='## Topic\n\nClinical text.\n\n- (a)For more information on a book: Textbook title.\nhttps://example.invalid/book\n\n- aIf a condition applies, see the original protocol.\n'
        b=parse(raw,'footnotes.md','Clinical Guideline Chapter')['blocks']
        self.assertEqual(next(x for x in b if 'example.invalid' in x['text'])['role'],'references')
        self.assertEqual(next(x for x in b if 'aIf a condition' in x['text'])['role'],'body')

    def test_single_terminal_reference_is_not_treatment(self):
        raw='\n\n'.join(['Body instructions.']*8)+"\n\n- 1.World Health Organization. Treatment report 2020.\nhttps://example.invalid/ref\n"
        b=parse(raw,'refs.md','Clinical Guideline Chapter')['blocks']
        self.assertEqual(b[-1]['role'],'references')

    def test_glued_abstract_heading_does_not_lose_query_word(self):
        p=parse('ABSTRACTPregnancy alters malaria medicine exposure.','abstract.md','Peer-reviewed Article')
        self.assertIn('ABSTRACT Pregnancy',p['blocks'][0]['text'])

    def test_proximity_uses_complete_topic_not_substrings(self):
        self.assertEqual(minimum_span(['child','cholera','severe','dehydration'],{'cholera','dehydration'}),3)
        self.assertIsNone(minimum_span(['living','survivors'],{'iv','ors'}))

    def test_candidate_diversity_prevents_reference_starvation(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.executescript(SCHEMA)
        for name,language in [('long.md','en'),('focused.md','fr')]:
            c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)',(name,'hash',name,'filename','Report',language,'content','[]',''))
            r=c.execute('INSERT INTO document_rows(doc_id) VALUES(?)',(name,))
            c.execute('INSERT INTO document_fts(rowid,title,body) VALUES(?,?,?)',(r.lastrowid,'','needle treatment'))
        for i in range(220):
            name='long.md' if i<219 else 'focused.md'
            role='references' if i<219 else 'body'
            r=c.execute('INSERT INTO passages(doc_id,section,text,role,line_start,line_end) VALUES(?,?,?,?,?,?)',(name,'','needle treatment',role,1,1))
            c.execute('INSERT INTO passage_fts(rowid,title,section,body) VALUES(?,?,?,?)',(r.lastrowid,'','','needle treatment'))
        rows=retrieve(c,'"needle" OR "treatment"','',[])
        self.assertIn('focused.md',[x['doc_id'] for x in rows])
        self.assertLessEqual(sum(x['doc_id']=='long.md' for x in rows),4)
        filtered=retrieve(c,'"needle"',' AND d.language=?',['fr'])
        self.assertEqual({x['doc_id'] for x in filtered},{'focused.md'})
        c.close()

    def test_moved_package_uses_packaged_sources(self):
        import shutil
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'data').mkdir();(root/'Parsed').mkdir()
            shutil.copy2(self.db,root/'data/search.sqlite')
            p=self.root/'Parsed/P01.md';raw=p.read_bytes()
            (root/'Parsed/P01.md').write_bytes(raw)
            try:
                p.write_text('Changed at old build path')
                self.assertEqual(document(root/'data/search.sqlite','P01.md')['text'],raw.decode())
            finally:
                p.write_bytes(raw)

    def test_review_overlay_is_bound_to_original_hash(self):
        analysis=self.root/'analysis';analysis.mkdir(exist_ok=True)
        overlay=analysis/'guideline_content_review.json'
        source=self.root/'Parsed/Dfront.md'
        r={'role':'introduction_or_cover','raw_hash':hashlib.sha256(source.read_bytes()).hexdigest(),
           'reason':'Tested source structure','warnings':[{'code':'example_warning'}]}
        try:
            overlay.write_text(json.dumps({'files':{'Dfront.md':r}}))
            db=self.root/'data/review.sqlite'
            with contextlib.redirect_stdout(io.StringIO()): build(self.root,db)
            result=search(db,'Dfront.md')['results'][0]
            self.assertEqual(result['review']['role'],'introduction_or_cover')
            self.assertIn('example_warning',result['quality'])
            r['raw_hash']='invalid'
            overlay.write_text(json.dumps({'files':{'Dfront.md':r}}))
            with contextlib.redirect_stdout(io.StringIO()): build(self.root,db)
            self.assertIsNone(search(db,'Dfront.md')['results'][0]['review'])
        finally:
            overlay.unlink(missing_ok=True)

    @contextlib.contextmanager
    def paging_database(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'paging.sqlite'
            shutil.copy2(self.db,db)
            c=sqlite3.connect(db)
            for i in range(14):
                name=f'Page{i:02}.md';text=f'Needle sharedtopic useful passage number {i}.'
                c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)',(name,str(i),name,'filename','Report','en','content','[]',''))
                c.execute('INSERT INTO sources VALUES(?,?,?,?,?)',(name,name,'Report','en',str(i)))
                row=c.execute('INSERT INTO passages(doc_id,section,text,role,line_start,line_end) VALUES(?,?,?,?,?,?)',(name,'',text,'body',1,1))
                c.execute('INSERT INTO passage_fts(rowid,title,section,body) VALUES(?,?,?,?)',(row.lastrowid,'','',normalize(text)))
                docrow=c.execute('INSERT INTO document_rows(doc_id) VALUES(?)',(name,))
                c.execute('INSERT INTO document_fts(rowid,title,body) VALUES(?,?,?)',(docrow.lastrowid,'',normalize(text)))
            c.commit();c.close()
            yield db

    def test_more_than_ten_results_are_pageable_without_duplicates(self):
        with self.paging_database() as db:
            first=search(db,'needle sharedtopic',limit=10)
            second=search(db,'needle sharedtopic',limit=10,offset=10)
            self.assertEqual(first['total_results'],14)
            self.assertEqual(len(first['results']),10)
            self.assertTrue(first['has_more'])
            self.assertEqual(len(second['results']),4)
            self.assertFalse(second['has_more'])
            files=[r['filename'] for r in first['results']+second['results']]
            self.assertEqual(len(files),len(set(files)))
            all_at_once=search(db,'needle sharedtopic',limit=50)
            self.assertEqual(files,[r['filename'] for r in all_at_once['results']])

    def test_partial_keyword_candidates_are_not_used_to_fill_page(self):
        r=search(self.db,'cholera severe dehydration',limit=10)
        self.assertEqual(len(r['results']),1)
        self.assertEqual(r['total_results'],1)
        self.assertGreater(r['hidden_partial_count'],0)
        broad=search(self.db,'cholera severe dehydration',include_partial=True,limit=50)
        self.assertGreater(broad['total_results'],1)
        self.assertTrue(any(x['match_kind']=='partial_keyword' for x in broad['results']))

    def test_no_complete_topic_match_reports_hidden_partials(self):
        with self.paging_database() as db:
            r=search(db,'needle unknownconditionzz')
            self.assertEqual(r['results'],[])
            self.assertEqual(r['total_results'],0)
            self.assertEqual(r['hidden_partial_count'],14)
            self.assertEqual(r['evidence'],'limited')
            self.assertIn('Enable partial keyword matches',r['message'])
            broad=search(db,'needle unknownconditionzz',include_partial=True,limit=20)
            self.assertEqual(len(broad['results']),14)

    def test_dense_only_candidate_remains_visible_without_english_words(self):
        c=connect(self.db)
        pid=c.execute("SELECT id FROM passages WHERE doc_id='Dar.md' LIMIT 1").fetchone()[0]
        c.close()
        class Semantic:
            def search(self,query,limit,allowed):
                return [pid]
        r=search(self.db,'cholera children dehydration',dense=Semantic())
        arabic=next(x for x in r['results'] if x['filename']=='Dar.md')
        self.assertEqual(arabic['match_kind'],'semantic')
        self.assertEqual(arabic['topic_match'],'semantic')
        self.assertEqual(arabic['matched_terms'],[])

    def test_exact_filename_pagination_does_not_repeat_record(self):
        r=search(self.db,'P01.md',offset=1)
        self.assertEqual(r['total_results'],1)
        self.assertEqual(r['results'],[])
        self.assertFalse(r['has_more'])

    def test_language_correction_preserves_supplied_csv_and_raw_sources(self):
        analysis=self.root/'analysis';analysis.mkdir(exist_ok=True)
        overlay=analysis/'source_language_review.json'
        filename='P01.md'
        raw_hash=hashlib.sha256((self.root/'Parsed'/filename).read_bytes()).hexdigest()
        row={'raw_hash':raw_hash,'supplied_language':'en','detected_language':'fr',
             'effective_language':'fr','method':'test_fixture_override'}
        try:
            overlay.write_text(json.dumps({'files':{filename:row}}))
            db=self.root/'data/language.sqlite'
            with contextlib.redirect_stdout(io.StringIO()): build(self.root,db)
            result=search(db,filename)['results'][0]
            self.assertEqual(result['language'],'fr')
            self.assertEqual(result['supplied_language'],'en')
            self.assertEqual(document(db,filename)['supplied_language'],'en')
            self.assertEqual(hashlib.sha256((self.root/'Parsed'/filename).read_bytes()).hexdigest(),raw_hash)
            # A stale language review cannot override fresh input metadata.
            row['raw_hash']='stale'
            overlay.write_text(json.dumps({'files':{filename:row}}))
            with contextlib.redirect_stdout(io.StringIO()): build(self.root,db)
            self.assertEqual(search(db,filename)['results'][0]['language'],'en')
        finally:
            overlay.unlink(missing_ok=True)

    def test_changed_source_detected(self):
        p=self.root/'Parsed/Dvariant.md'
        original=p.read_bytes()
        try:
            p.write_text('Changed content')
            with self.assertRaises(ValueError):
                document(self.db,p.name)
        finally:
            p.write_bytes(original)

    def test_different_sources_not_silently_merged(self):
        c=connect(self.db)
        ids=[r[0] for r in c.execute("SELECT doc_id FROM sources WHERE filename IN ('P01.md','Dvariant.md')")]
        c.close()
        self.assertEqual(len(set(ids)),2)


if __name__=='__main__':
    unittest.main()
