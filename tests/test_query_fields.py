"""Query edits must affect retrieval, not just decorate the UI."""
import contextlib
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from build_index import build
from local_search.search import search


class QueryFieldRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls.temp.name)
        (root/'Parsed').mkdir()
        docs = [
            ('cholera.md', '# Cholera\n\nCholera treatment in children with severe dehydration.', 'Clinical Guideline Chapter', 'en'),
            ('tb.md', '# Tuberculosis\n\nPulmonary tuberculosis treatment for adults.', 'Clinical Guideline Chapter', 'en'),
            ('flu_en.md', '# Influenza\n\nInfluenza treatment document with substantive clinical information.', 'Report', 'en'),
            # Same raw bytes with a distinct supplied genre/language label.
            ('flu_fr.md', '# Influenza\n\nInfluenza treatment document with substantive clinical information.', 'Peer-reviewed Article', 'fr'),
        ]
        with (root/'D4GC Challenge 2026 Documentation.csv').open('w',newline='') as f:
            writer=csv.writer(f);writer.writerow(['id','genre','language'])
            for name,text,genre,language in docs:
                (root/'Parsed'/name).write_text(text)
                writer.writerow([Path(name).stem,genre,language])
        with contextlib.redirect_stdout(io.StringIO()):
            build(root)
        cls.db=root/'data/search.sqlite'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_unedited_request_is_preserved(self):
        q='Cholera treatment guidelines for children with severe dehydration'
        response=search(self.db,q)
        self.assertEqual(response['retrieval_query'],q)
        self.assertEqual(response['query'],q)

    def test_edit_changes_candidates_and_keeps_original_request(self):
        r=search(self.db,'cholera treatment',facets={'condition':'tuberculosis','task':'treatment'})
        self.assertEqual(r['query'],'cholera treatment')
        self.assertEqual(r['retrieval_query'],'tuberculosis treatment')
        self.assertEqual(r['results'][0]['filename'],'tb.md')
        self.assertNotIn('cholera.md',[x['filename'] for x in r['results']])

    def test_explicit_empty_fields_stay_removed(self):
        r=search(self.db,'cholera treatment',facets={'condition':'','task':''})
        self.assertIsNone(r['facets']['condition'])
        self.assertIsNone(r['facets']['task'])
        self.assertEqual(r['retrieval_query'],'')
        self.assertEqual(r['results'],[])

    def test_preference_is_soft_and_does_not_become_topic_word(self):
        r=search(self.db,'cholera',facets={'preferred_source':'peer-reviewed article'})
        self.assertEqual(r['retrieval_query'],'cholera')
        self.assertEqual(r['results'][0]['filename'],'cholera.md')

    def test_reranker_failure_preserves_retrieval_and_is_reported(self):
        class BrokenReranker:
            def rerank(self,*args,**kwargs):
                raise RuntimeError('local inference failed')
        baseline=search(self.db,'cholera treatment',include_partial=True)
        with patch('local_search.reranker.query_eligibility',return_value=(True,'English')):
            response=search(self.db,'cholera treatment',include_partial=True,reranker=BrokenReranker())
        self.assertEqual(response['rerank_status'],'fallback')
        self.assertIn('failed',response['rerank_note'])
        self.assertEqual([x['doc_id'] for x in response['results']],
                         [x['doc_id'] for x in baseline['results']])

    def test_combined_filters_must_match_same_alias(self):
        # en occurs on the report alias, while the article alias is fr.
        self.assertFalse(search(self.db,'influenza',language='en',genre='Peer-reviewed Article')['results'])
        r=search(self.db,'influenza',language='fr',genre='Peer-reviewed Article')['results'][0]
        self.assertEqual((r['filename'],r['language'],r['genre']),('flu_fr.md','fr','Peer-reviewed Article'))
        self.assertEqual({x['filename'] for x in r['sources']},{'flu_en.md','flu_fr.md'})


if __name__=='__main__':
    unittest.main()
