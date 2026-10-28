"""Query-editing and optional reranking integrity checks.

These tests check source retrieval and honest fallback behavior. They do not
validate medical advice or convert uncalibrated model logits into confidence.
"""
import contextlib
import copy
import importlib.util
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

from local_search.ingest import tokens
from local_search.search import (edited_query, parse_query, query_terms,
                                 refresh_passage_evidence, search)
from local_search.reranker import LocalReranker, RerankerError, query_eligibility

ROOT = Path(__file__).resolve().parent.parent
HAS_RUNTIME = all(importlib.util.find_spec(name) is not None for name in
                  ('numpy', 'torch', 'sentence_transformers', 'langid'))
HAS_MODELS = ((ROOT / 'models/reranker/model.safetensors').is_file()
              and (ROOT / 'models/multilingual-e5-small/model.safetensors').is_file()
              and (ROOT / 'data/search.sqlite').is_file()
              and (ROOT / 'data/embedding_manifest.json').is_file())


@contextlib.contextmanager
def no_network():
    error = AssertionError('Retrieval tests must not access the network')
    with patch.object(socket.socket, 'connect', side_effect=error), \
         patch('socket.create_connection', side_effect=error):
        yield


class QueryEditingTests(unittest.TestCase):
    def test_common_slots_preserve_condition_and_context(self):
        fields = parse_query('Cholera treatment guidelines for children with severe dehydration')
        self.assertEqual(tokens(fields['condition']), ['cholera'])
        self.assertEqual(fields['population'], 'children')
        self.assertEqual(fields['severity'], 'severe dehydration')
        self.assertIn('treatment', fields['task'])
        self.assertEqual(fields['preferred_source'], 'clinical guideline')

    def test_accented_phrases_are_consumed_without_stray_condition(self):
        for query in ('deshidratación severa guía de tratamiento',
                      'déshydratation sévère chez les enfants'):
            with self.subTest(query=query):
                fields = parse_query(query)
                self.assertIsNone(fields['condition'])
                self.assertEqual(fields['severity'], 'severe dehydration')
        fields = parse_query('tuberculose traitement chez les enfants')
        self.assertEqual(tokens(fields['condition']), ['tuberculose'])
        self.assertEqual(fields['population'], 'children')

    def test_task_only_request_does_not_fabricate_condition(self):
        self.assertIsNone(parse_query('treatment guidelines')['condition'])
        self.assertIsNone(parse_query('')['condition'])

    def test_unknown_condition_is_preserved(self):
        self.assertEqual(parse_query('unrecognized-topic treatment')['condition'],
                         'unrecognized topic')

    def test_explicit_negation_is_preserved_in_interpreted_fields(self):
        cases = (
            ('cholera without dehydration', 'severity', 'without dehydration'),
            ('cholera not severe', 'severity', 'not severe'),
            ('cholera not in children', 'population', 'not in children'),
        )
        for query, field, expected in cases:
            with self.subTest(query=query):
                fields = parse_query(query)
                self.assertEqual(fields[field], expected)
                self.assertEqual(tokens(fields['condition']), ['cholera'])

    def test_no_edits_keeps_original_query_verbatim(self):
        query = '  Cholera without dehydration?  '
        self.assertEqual(edited_query(query, parse_query(query), None), query)

    def test_removing_population_changes_retrieval_query(self):
        query = 'cholera treatment for children'
        fields = parse_query(query)
        updated = edited_query(query, fields, {'population': ''})
        self.assertIsNone(fields['population'])
        self.assertNotIn('child', tokens(updated))
        self.assertIn('cholera', tokens(updated))
        self.assertIn('treatment', tokens(updated))

    def test_replacing_condition_and_population_changes_retrieval_terms(self):
        query = 'cholera treatment for children'
        updated = edited_query(query, parse_query(query),
                               {'condition': 'tuberculosis', 'population': 'adults'})
        self.assertIn('tuberculosis', tokens(updated))
        self.assertIn('adults', tokens(updated))
        self.assertNotIn('cholera', tokens(updated))
        self.assertNotIn('child', tokens(updated))

    def test_invalid_facet_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'text'):
            edited_query('cholera', parse_query('cholera'), {'condition': ['tuberculosis']})


class FakeModel:
    def __init__(self, scores=None, error=None):
        self.scores = scores
        self.error = error
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append(pairs)
        if self.error:
            raise self.error
        return self.scores


def passage(identifier, text='Primary content', section='Introduction', role='body'):
    return {'id': identifier, 'text': text, 'section': section, 'role': role,
            'line_start': identifier, 'line_end': identifier}


def record(name, identifier, language='en', genre='Peer-reviewed Article'):
    return {'doc_id': name, 'filename': name, 'language': language, 'genre': genre,
            'title': 'Opening excerpt with unrelated keywords', 'title_source': 'opening_excerpt',
            'passage': passage(identifier), 'other_passages': []}


class RerankerIntegrityTests(unittest.TestCase):
    def reranker(self, scores=None, error=None):
        reranker = LocalReranker.__new__(LocalReranker)
        reranker.model = FakeModel(scores, error)
        return reranker

    def test_nonfinite_incomplete_and_malformed_predictions_preserve_inputs(self):
        original = [record('a.md', 1), record('b.md', 2)]
        snapshot = copy.deepcopy(original)
        for scores in ([1.0], [1.0, float('nan')], [float('inf'), 1.0], [[1.0], [2.0]]):
            with self.subTest(scores=scores):
                reranker = self.reranker(scores)
                with self.assertRaises(RerankerError):
                    reranker.rerank('tuberculosis treatment', original, query_language='en')
                self.assertEqual(original, snapshot)

    def test_prediction_exception_is_explicit_and_inputs_unchanged(self):
        original = [record('a.md', 1)]
        snapshot = copy.deepcopy(original)
        with self.assertRaises(RerankerError):
            self.reranker(error=RuntimeError('runtime failed')).rerank(
                'tuberculosis treatment', original, query_language='en')
        self.assertEqual(original, snapshot)

    def test_passage_swap_restores_old_primary_without_duplicate_alternatives(self):
        original = record('a.md', 1)
        alternate = passage(2, 'Treatment content', 'Treatment')
        original['other_passages'] = [alternate, copy.deepcopy(alternate)]
        snapshot = copy.deepcopy(original)
        reranker = self.reranker([0.0, 1.0])
        updated = reranker.rerank('tuberculosis treatment', [original], query_language='en')[0]
        self.assertEqual(updated['passage']['id'], 2)
        self.assertEqual([p['id'] for p in updated['other_passages']], [1])
        self.assertTrue(updated['reranked'])
        self.assertEqual(original, snapshot)
        self.assertEqual(len(reranker.model.calls[0]), 2)

    def test_other_language_positions_and_candidates_outside_limit_are_fixed(self):
        original = [record('a.md', 1), record('fr.md', 2, language='fr'),
                    record('b.md', 3), record('later.md', 4)]
        updated = self.reranker([0.0, 1.0]).rerank(
            'tuberculosis treatment', original, top_k=3, query_language='en')
        self.assertEqual([r['doc_id'] for r in updated],
                         ['b.md', 'fr.md', 'a.md', 'later.md'])
        self.assertIs(updated[1], original[1])
        self.assertIs(updated[3], original[3])

    def test_ineligible_document_is_not_scored_or_reordered(self):
        original = [record('unknown-drug.md', 1), record('allowed.md', 2)]
        reranker = self.reranker([1.0])
        updated = reranker.rerank('antibiotic dosage', original,
                                 eligible={'allowed.md'}, query_language='en')
        self.assertIs(updated[0], original[0])
        self.assertNotIn('rerank_score', updated[0])
        self.assertTrue(updated[1]['reranked'])
        self.assertEqual(len(reranker.model.calls[0]), 1)

    def test_clinical_intent_does_not_add_arbitrary_genre_logits(self):
        original = [record('report.md', 1, genre='Financial Report'),
                    record('guideline.md', 2, genre='Clinical Guideline Chapter')]
        updated = self.reranker([0.25, 0.25]).rerank(
            'tuberculosis treatment', original, clinical_intent=True, query_language='en')
        self.assertEqual([r['doc_id'] for r in updated], ['report.md', 'guideline.md'])
        self.assertEqual([r['rerank_score'] for r in updated], [0.25, 0.25])

    def test_opening_excerpt_is_not_repeated_as_a_title(self):
        reranker = self.reranker([1.0])
        reranker.rerank('tuberculosis treatment', [record('a.md', 1)], query_language='en')
        self.assertNotIn('Opening excerpt', reranker.model.calls[0][0][1])

    def test_reference_only_candidate_is_not_scored(self):
        original = record('reference.md', 1)
        original['passage']['role'] = 'references'
        reranker = self.reranker(error=AssertionError('Must not score reference-only candidate'))
        self.assertEqual(reranker.rerank('tuberculosis treatment', [original], query_language='en'), [original])
        self.assertEqual(reranker.model.calls, [])

    def test_non_english_query_skips_model(self):
        original = [record('a.md', 1)]
        reranker = self.reranker(error=AssertionError('Unsupported language must skip prediction'))
        self.assertEqual(reranker.rerank('tuberculose traitement', original,
                                        query_language='fr'), original)
        self.assertEqual(reranker.model.calls, [])
        self.assertFalse(query_eligibility('déshydratation sévère')[0])
        self.assertFalse(query_eligibility('TB')[0])

    def test_cpu_only_configuration_is_enforced_before_loading(self):
        with self.assertRaisesRegex(ValueError, 'CPU'):
            LocalReranker('/unused', device='mps')


class PassageEvidenceTests(unittest.TestCase):
    def test_evidence_is_refreshed_to_selected_passage(self):
        row = record('a.md', 1)
        row.update(matched_terms=['cholera'], missing_terms=['treatment'],
                   topic_match='full', match_kind='word_match')
        row['passage'] = passage(2, 'Tuberculosis treatment content', 'Treatment')
        terms = query_terms('cholera treatment')
        refresh_passage_evidence(row, terms, {'cholera'}, {2})
        self.assertEqual(row['matched_terms'], ['treatment'])
        self.assertEqual(row['missing_terms'], ['cholera'])
        self.assertEqual(row['topic_match'], 'semantic')
        self.assertEqual(row['match_kind'], 'semantic')
        refresh_passage_evidence(row, terms, {'cholera'}, set())
        self.assertEqual(row['topic_match'], 'partial')
        self.assertEqual(row['match_kind'], 'partial_keyword')

    def test_full_word_match_uses_selected_content_without_opening_excerpt(self):
        row = record('a.md', 1)
        row['title'] = 'Cholera treatment'
        row['passage'] = passage(2, 'Different subject', 'Introduction')
        refresh_passage_evidence(row, ['cholera', 'treatment'], {'cholera'}, set())
        self.assertEqual(row['matched_terms'], [])
        row['passage'] = passage(3, 'Cholera treatment', 'Treatment')
        refresh_passage_evidence(row, ['cholera', 'treatment'], {'cholera'}, set())
        self.assertEqual(row['topic_match'], 'full')
        self.assertEqual(row['missing_terms'], [])


@unittest.skipUnless(HAS_RUNTIME and HAS_MODELS,
                     'Local corpus and E5/reranker runtimes are required; nothing is downloaded')
class OfflineCorpusRerankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from local_search.embeddings import DenseIndex
        cls.db = ROOT / 'data/search.sqlite'
        with no_network():
            cls.dense = DenseIndex(cls.db)
            cls.reranker = LocalReranker(ROOT / 'models/reranker')

    @classmethod
    def tearDownClass(cls):
        del cls.dense
        del cls.reranker

    def test_reviewed_tuberculosis_and_postpartum_sources_remain_findable(self):
        for query, expected in (('pulmonary tuberculosis treatment', 'P21.md'),
                                ('postpartum hemorrhage management', 'P23.md')):
            with self.subTest(query=query), no_network():
                result = search(self.db, query, dense=self.dense, reranker=self.reranker, limit=5)
                self.assertEqual(result['mode'], 'hybrid')
                self.assertIn(expected, [r['filename'] for r in result['results']])
                self.assertIn(result['rerank_status'], {'applied', 'skipped'})
                self.assertTrue(result.get('rerank_note'))
                if query == 'pulmonary tuberculosis treatment':
                    self.assertEqual(result['rerank_status'], 'applied')
                    self.assertTrue(any(r.get('reranked') for r in result['results']))

    def test_missing_drug_identity_is_preserved_on_exact_lookup(self):
        with no_network():
            result = search(self.db, 'P24.md', dense=self.dense, reranker=self.reranker)
        row = result['results'][0]
        self.assertEqual(row['filename'], 'P24.md')
        self.assertIn('missing_drug_identity', row['quality'])
        self.assertIn('missing_drug_identity', [w['code'] for w in row['review']['warnings']])
        self.assertFalse(row.get('reranked', False))
        self.assertNotIn('amoxicillin', row['title'].casefold())

    def test_french_query_retains_hybrid_results_and_skips_english_reranker(self):
        with no_network():
            baseline = search(self.db, 'tuberculose traitement', language='fr', dense=self.dense)
            result = search(self.db, 'tuberculose traitement', language='fr',
                            dense=self.dense, reranker=self.reranker)
        self.assertEqual(result['mode'], 'hybrid')
        self.assertEqual(result['rerank_status'], 'skipped')
        self.assertEqual([r['filename'] for r in result['results']],
                         [r['filename'] for r in baseline['results']])
        self.assertIn('P22.md', [r['filename'] for r in result['results']])
        self.assertFalse(any(r.get('reranked') for r in result['results']))


if __name__ == '__main__':
    unittest.main()
