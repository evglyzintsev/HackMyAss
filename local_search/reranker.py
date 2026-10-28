"""Optional English passage reranker, loaded only from local safetensors files.

The downloaded MS MARCO model was trained for English retrieval. It must not
replace multilingual retrieval rankings with unsupported cross-language scores.
"""
import functools
import math
import os
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['DO_NOT_TRACK'] = '1'


class RerankerError(RuntimeError):
    """A local reranking attempt failed; retain the original retrieval order."""


@functools.lru_cache(maxsize=1)
def _language_identifier():
    from langid.langid import LanguageIdentifier, model
    return LanguageIdentifier.from_modelstring(model, norm_probs=True)


@functools.lru_cache(maxsize=16)
def query_eligibility(query):
    """Conservatively identify English requests; uncertainty skips reranking.

    This is only a model compatibility guard. It does not reinterpret a request,
    filter sources, or assert that the detected language is correct.
    """
    if len(query.split()) < 2 or len(query) < 8:
        return False, 'The English reranker is skipped for a short or ambiguous query.'
    if any(ch.isalpha() and not ch.isascii() for ch in query):
        return False, 'The English reranker is skipped for a possibly non-English query.'
    try:
        language, probability = _language_identifier().classify(query)
    except Exception:
        return False, 'Query language could not be checked locally; the English reranker is skipped.'
    if language != 'en' or probability < .9:
        return False, 'The English reranker is skipped because query language is uncertain or not English.'
    return True, 'English query candidates can be reranked locally; other language positions are retained.'


def _passage_key(passage):
    if passage.get('id') is not None:
        return ('id', passage['id'])
    return ('span', passage.get('line_start'), passage.get('line_end'), passage.get('text'))


class LocalReranker:
    def __init__(self, model_path, device='cpu', max_length=256):
        if device != 'cpu':
            raise ValueError('The serving reranker is configured for CPU only.')
        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.is_dir():
            raise FileNotFoundError(f'Local reranker directory not found: {model_path}')
        if not (self.model_path / 'model.safetensors').is_file():
            raise FileNotFoundError('The local reranker requires model.safetensors weights.')
        import torch
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(
            str(self.model_path), max_length=max_length, device='cpu',
            local_files_only=True, trust_remote_code=False,
            model_kwargs={'use_safetensors': True},
        )

    def rerank(self, query, candidate_records, top_k=10, clinical_intent=False,
               eligible=None, query_language=None):
        """Reorder eligible English slots within the first top_k candidates.

        ``eligible`` optionally limits eligible doc_ids further. ``query_language``
        may be supplied after a caller's conservative language check. All other
        language positions remain fixed. Genre is not a calibrated relevance
        signal, so this layer adds no genre-dependent model-logit adjustments.

        Predictions are validated before constructing result copies. An exception
        leaves the caller's records untouched and allows an explicit fallback.
        """
        if not candidate_records or top_k <= 0:
            return list(candidate_records)
        if query_language is None:
            supported, _ = query_eligibility(query)
        else:
            supported = query_language == 'en'
        if not supported:
            return list(candidate_records)

        slots = []
        pairs = []
        mapping = []
        for position, record in enumerate(candidate_records[:top_k]):
            if record.get('language') != 'en':
                continue
            if eligible is not None and record.get('doc_id') not in eligible:
                continue
            passages = []
            seen = set()
            for passage in [record.get('passage')] + list(record.get('other_passages', []))[:2]:
                if not passage or passage.get('role') == 'references' or not passage.get('text', '').strip():
                    continue
                key = _passage_key(passage)
                if key in seen:
                    continue
                seen.add(key)
                passages.append(passage)
            if not passages:
                continue
            slots.append(position)
            title = record.get('title', '') if record.get('title_source') != 'opening_excerpt' else ''
            for passage in passages:
                header = ' — '.join(s for s in (title, passage.get('section', '')) if s)
                text = '\n'.join(s for s in (header, passage['text']) if s)
                pairs.append((query, text))
                mapping.append((position, passage))

        if not pairs:
            return list(candidate_records)
        try:
            predictions = self.model.predict(pairs, show_progress_bar=False)
            scores = [float(value) for value in predictions]
            if len(scores) != len(mapping):
                raise ValueError('Prediction count does not match the passage count.')
            if not all(math.isfinite(value) for value in scores):
                raise ValueError('Predictions contain non-finite scores.')
        except Exception as exc:
            raise RerankerError('Local passage reranking failed; original retrieval order retained.') from exc

        best = {}
        for score, (position, passage) in zip(scores, mapping):
            if position not in best or score > best[position][0]:
                best[position] = (score, passage)

        ranked = []
        for position in slots:
            score, selected = best[position]
            original = candidate_records[position]
            updated = dict(original)
            selected_key = _passage_key(selected)
            alternatives = []
            seen = {selected_key}
            for passage in [original.get('passage')] + list(original.get('other_passages', [])):
                if not passage:
                    continue
                key = _passage_key(passage)
                if key not in seen:
                    alternatives.append(dict(passage))
                    seen.add(key)
            updated.update(
                rerank_score=score, reranked=True, passage=dict(selected),
                other_passages=alternatives,
            )
            ranked.append(updated)
        ranked.sort(key=lambda record: record['rerank_score'], reverse=True)
        output = list(candidate_records)
        for position, updated in zip(slots, ranked):
            output[position] = updated
        return output
