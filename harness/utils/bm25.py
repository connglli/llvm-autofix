"""Minimal BM25 index for ranking a small corpus of documents."""

import math
import re
from collections import Counter
from typing import Callable, Optional

_DEFAULT_K1 = 1.5
_DEFAULT_B = 0.75


def tokenize(text: str) -> list[str]:
  """Default tokenizer: split on word boundaries, lowercase."""
  return re.findall(r"\w+", text.lower())


class BM25Index:
  """BM25 index over a small corpus of documents.

  Args:
    corpus: Mapping of document key to either a raw text string or a
      pre-tokenized list of terms.
    k1: Term frequency saturation parameter.
    b: Length normalization parameter.
    tokenizer: Function to tokenize raw text strings. Defaults to
      :func:`tokenize`. Ignored for pre-tokenized (list) documents.
    match_fn: Function ``(query_term, doc_term) -> bool`` used to
      determine if a query term matches a document term. Defaults to
      exact equality. Use a substring matcher for fuzzy matching.
  """

  def __init__(
    self,
    corpus: dict[str, str | list[str]],
    k1: float = _DEFAULT_K1,
    b: float = _DEFAULT_B,
    tokenizer: Optional[Callable[[str], list[str]]] = None,
    match_fn: Optional[Callable[[str, str], bool]] = None,
  ):
    self._k1 = k1
    self._b = b
    self._tokenizer = tokenizer or tokenize
    self._match_fn = match_fn
    self._keys = list(corpus.keys())
    self._docs = [
      v if isinstance(v, list) else self._tokenizer(v) for v in corpus.values()
    ]
    self._doc_lens = [len(d) for d in self._docs]
    self._avgdl = sum(self._doc_lens) / max(len(self._docs), 1) or 1.0
    # Pre-compute document frequencies (only for exact matching)
    if self._match_fn is None:
      self._df: dict[str, int] = {}
      for doc in self._docs:
        for term in set(doc):
          self._df[term] = self._df.get(term, 0) + 1
    else:
      self._df = {}
    self._n = len(self._docs)

  def query(self, q: str | list[str], top_k: int = 5) -> list[tuple[str, float]]:
    """Return up to *top_k* (key, score) pairs sorted by descending BM25 score.

    Args:
      q: Query as a raw string (will be tokenized) or pre-tokenized list.
      top_k: Maximum number of results to return.
    """
    tokens = q if isinstance(q, list) else self._tokenizer(q)
    if not tokens:
      return []

    scores: list[tuple[str, float]] = []
    for i, doc in enumerate(self._docs):
      score = self._score_doc(tokens, doc, self._doc_lens[i])
      if score > 0:
        scores.append((self._keys[i], score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]

  def _score_doc(self, query_tokens: list[str], doc: list[str], doc_len: int) -> float:
    if self._match_fn is not None:
      return self._score_doc_fuzzy(query_tokens, doc, doc_len)
    return self._score_doc_exact(query_tokens, doc, doc_len)

  def _score_doc_exact(
    self, query_tokens: list[str], doc: list[str], doc_len: int
  ) -> float:
    tf = Counter(doc)
    score = 0.0
    for t in query_tokens:
      if t not in self._df:
        continue
      f = tf.get(t, 0)
      idf = math.log((self._n - self._df[t] + 0.5) / (self._df[t] + 0.5) + 1.0)
      denom = f + self._k1 * (1 - self._b + self._b * doc_len / self._avgdl)
      score += idf * (f * (self._k1 + 1)) / denom
    return score

  def _score_doc_fuzzy(
    self, query_tokens: list[str], doc: list[str], doc_len: int
  ) -> float:
    match_fn = self._match_fn
    # Compute per-query-term tf via custom match function
    tf_map: dict[str, int] = {}
    for doc_term in doc:
      for qt in query_tokens:
        if match_fn(qt, doc_term):
          tf_map[qt] = tf_map.get(qt, 0) + 1

    # df must be computed per-query since matching is fuzzy
    df: dict[str, int] = {}
    for qt in query_tokens:
      count = 0
      for j, other_doc in enumerate(self._docs):
        for dt in other_doc:
          if match_fn(qt, dt):
            count += 1
            break
      if count > 0:
        df[qt] = count

    score = 0.0
    dl = doc_len or 1
    for qt in query_tokens:
      f = tf_map.get(qt, 0)
      if f == 0:
        continue
      idf = math.log((self._n - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1.0)
      denom = f + self._k1 * (1 - self._b + self._b * dl / self._avgdl)
      score += idf * (f * (self._k1 + 1)) / denom
    return score
