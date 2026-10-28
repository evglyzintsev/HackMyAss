"""Small real-model checks. Skipped unless the local E5 model/runtime is present.

No network is permitted by these tests. They use a three-document temporary index,
not the production corpus, and share one loaded DenseIndex across test methods.
"""
import contextlib
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / 'models' / 'multilingual-e5-small'
HAS_RUNTIME = all(importlib.util.find_spec(name) is not None for name in
                  ('numpy', 'torch', 'sentence_transformers'))
HAS_MODEL = (MODEL / 'model.safetensors').is_file() and (MODEL / 'modules.json').is_file()


@contextlib.contextmanager
def no_network():
    error = AssertionError('Vector tests must never access the network')
    with patch.object(socket.socket, 'connect', side_effect=error), \
         patch('socket.create_connection', side_effect=error):
        yield


@unittest.skipUnless(HAS_RUNTIME and HAS_MODEL,
                     'Local multilingual E5 model and optional runtime are required; nothing is downloaded')
class RealVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from build_index import build
        from local_search.embeddings import build_vectors, DenseIndex
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        (cls.root / 'Parsed').mkdir()
        docs = {
            'FrenchTB.md': (
                '# Tuberculose pulmonaire\n\n## Diagnostic et traitement\n\n'
                'Ce chapitre concerne la tuberculose pulmonaire, une infection des poumons. '
                'Il décrit le diagnostic et le traitement de la tuberculose chez les adultes '
                'et les enfants. Il ne traite ni du choléra ni des finances.\n',
                'Clinical Guideline Chapter', 'fr'),
            'FrenchCholera.md': (
                '# Choléra\n\nCette référence concerne une épidémie de choléra et '
                'la contamination de l’eau. Son sujet est la diarrhée aiguë et la '
                'déshydratation, pas les infections pulmonaires.\n',
                'Project Update', 'fr'),
            'Finance.md': (
                '# Annual financial statements\n\nThis financial report lists budgets, '
                'operating expenses, fundraising revenue, assets and liabilities. '
                'It does not provide disease diagnosis or treatment instructions.\n',
                'Financial Report', 'en'),
        }
        with (cls.root / 'D4GC Challenge 2026 Documentation.csv').open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'genre', 'language'])
            for name, (text, genre, language) in docs.items():
                (cls.root / 'Parsed' / name).write_text(text, encoding='utf-8')
                writer.writerow([Path(name).stem, genre, language])
        cls.db = cls.root / 'data' / 'search.sqlite'
        # Covers both real local model loading and embedding computation with outbound
        # socket connections forbidden, rather than trusting offline environment flags.
        try:
            with no_network(), contextlib.redirect_stdout(io.StringIO()):
                build(cls.root)
                build_vectors(cls.db, MODEL, device='cpu', batch_size=4)
                cls.dense = DenseIndex(cls.db)
        except BaseException:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        del cls.dense
        cls.temp.cleanup()

    def test_english_query_retrieves_french_tuberculosis_passage(self):
        with no_network():
            ids = self.dense.search('How is pulmonary tuberculosis diagnosed and treated?', limit=3)
        with sqlite3.connect(self.db) as c:
            top_source = c.execute('SELECT doc_id FROM passages WHERE id=?', (ids[0],)).fetchone()[0]
        self.assertEqual(top_source, 'FrenchTB.md')
        self.assertTrue(self.dense.last_scores[ids[0]] > self.dense.last_scores[ids[-1]])

    def test_vectors_are_normalized_and_cover_every_passage(self):
        import numpy as np
        self.assertEqual(self.dense.vectors.dtype, np.float32)
        self.assertEqual(self.dense.vectors.shape[1], 384)
        self.assertEqual(self.dense.vectors.shape[0], len(self.dense.ids))
        self.assertTrue(np.isfinite(self.dense.vectors).all())
        np.testing.assert_allclose(np.linalg.norm(self.dense.vectors, axis=1), 1., atol=1e-4)
        with sqlite3.connect(self.db) as c:
            passage_ids = {r[0] for r in c.execute('SELECT id FROM passages')}
        self.assertEqual(set(self.dense.ids.tolist()), passage_ids)

    def test_allowed_passage_filter_is_respected(self):
        with sqlite3.connect(self.db) as c:
            finance = c.execute("SELECT id FROM passages WHERE doc_id='Finance.md'").fetchone()[0]
        with no_network():
            self.assertEqual(self.dense.search('tuberculosis treatment', allowed={finance}), [finance])
            self.assertEqual(self.dense.search('tuberculosis treatment', allowed=set()), [])

    def test_token_windows_fit_limit_and_keep_document_tail(self):
        from local_search.embeddings import passage_windows
        model = self.dense.model
        text = ('Ce paragraphe décrit une référence médicale. ' * 150) + ' distinctive end marker zirconium'
        row = {'id': 987, 'title': 'Reference heading ' * 20, 'title_source': 'heading',
               'section': 'Long source context ' * 20, 'text': text}
        ids, windows = passage_windows(model, [row])
        self.assertGreater(len(windows), 1)
        self.assertEqual(set(ids), {987})
        self.assertTrue(all(w.startswith('passage: ') for w in windows))
        self.assertTrue(all(len(model.tokenizer.encode(w, add_special_tokens=True)) <= model.max_seq_length
                            for w in windows))
        self.assertIn('zirconium', windows[-1])

    def test_embedding_cache_resumes_without_reencoding_cached_windows(self):
        import numpy as np
        from local_search.embeddings import encode_cached, passage_windows
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        rows = c.execute('SELECT p.*,d.title,d.title_source FROM passages p '
                         'JOIN documents d USING(doc_id) ORDER BY p.id').fetchall()
        c.close()
        _, texts = passage_windows(self.dense.model, rows)
        cache = self.root / 'data' / 'vector_cache.sqlite'
        with no_network(), patch.object(self.dense.model, 'encode', side_effect=AssertionError('Cache miss')):
            with contextlib.redirect_stdout(io.StringIO()):
                resumed = encode_cached(self.dense.model, texts, cache,
                                        self.dense.info['model_sha256'], batch_size=4)
        np.testing.assert_array_equal(resumed, self.dense.vectors)
        # A resumed partial batch only computes the newly added window.
        new_text = 'passage: This new reference discusses refugee mental health services.'
        with no_network(), patch.object(self.dense.model, 'encode', wraps=self.dense.model.encode) as encoder:
            with contextlib.redirect_stdout(io.StringIO()):
                partial = encode_cached(self.dense.model, [texts[0], new_text], cache,
                                        self.dense.info['model_sha256'], batch_size=4)
        self.assertEqual(encoder.call_count, 1)
        self.assertEqual(encoder.call_args.args[0], [new_text])
        np.testing.assert_array_equal(partial[0], self.dense.vectors[0])

    def test_wrong_text_build_rejected_before_loading_model(self):
        from local_search.embeddings import DenseIndex
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            for name in ('search.sqlite', 'embeddings.npz', 'embedding_manifest.json'):
                shutil.copy2(self.root / 'data' / name, target / name)
            with sqlite3.connect(target / 'search.sqlite') as c:
                c.execute("UPDATE manifest SET value=? WHERE key='build_id'", (json.dumps('different-build'),))
            with no_network(), patch('local_search.embeddings.load_model',
                                     side_effect=AssertionError('Must reject stale build before model load')):
                with self.assertRaisesRegex(ValueError, 'another text build'):
                    DenseIndex(target / 'search.sqlite')

    def test_dense_candidates_are_diverse_before_rank_fusion(self):
        import numpy as np
        from local_search.embeddings import DenseIndex
        index=DenseIndex.__new__(DenseIndex)
        index.np=np
        index.ids=np.arange(1,21,dtype=np.int64)
        vector=np.ones(384,dtype=np.float32)/np.sqrt(384)
        index.vectors=np.tile(vector,(20,1))
        index.passage_docs={i:('long.md' if i<=18 else f'focused{i}.md') for i in range(1,21)}
        index.reference_ids=set(range(1,17))
        index._query_cache={'same query':vector}
        with no_network():
            result=index.search('same query',limit=10)
        self.assertIn(19,result)
        self.assertIn(20,result)
        self.assertLessEqual(sum(index.passage_docs[i]=='long.md' for i in result),4)
        self.assertNotIn(result[0],index.reference_ids)

    def test_repeated_query_uses_memory_cache_and_normalized_query(self):
        import numpy as np
        query = 'A local query for the offline cache test'
        with no_network():
            self.dense.search(query)
        np.testing.assert_allclose(np.linalg.norm(self.dense._query_cache[query]), 1., atol=1e-4)
        with no_network(), patch.object(self.dense.model, 'encode', side_effect=AssertionError('Query reencoded')):
            self.assertTrue(self.dense.search(query))
        self.assertEqual(os.environ['HF_HUB_OFFLINE'], '1')
        self.assertEqual(os.environ['TRANSFORMERS_OFFLINE'], '1')


if __name__ == '__main__':
    unittest.main()
