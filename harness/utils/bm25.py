"""Minimal BM25 index for ranking a small corpus of documents."""

import math
import re
from collections import Counter

_DEFAULT_K1 = 1.5
_DEFAULT_B = 0.75


def tokenize(text: str) -> list[str]:
  return re.findall(r"\w+", text.lower())


class BM25Index:
  """BM25 index over a small corpus of documents."""

  def __init__(
    self, corpus: dict[str, str], k1: float = _DEFAULT_K1, b: float = _DEFAULT_B
  ):
    self._k1 = k1
    self._b = b
    self._keys = list(corpus.keys())
    self._docs = [tokenize(corpus[k]) for k in self._keys]
    self._doc_lens = [len(d) for d in self._docs]
    self._avgdl = sum(self._doc_lens) / max(len(self._docs), 1)
    self._df: dict[str, int] = {}
    for doc in self._docs:
      for term in set(doc):
        self._df[term] = self._df.get(term, 0) + 1
    self._n = len(self._docs)

  def query(self, q: str, top_k: int = 5) -> list[tuple[str, float]]:
    """Return up to *top_k* (key, score) pairs sorted by descending BM25 score."""
    tokens = tokenize(q)
    scores: list[tuple[str, float]] = []
    for i, doc in enumerate(self._docs):
      tf = Counter(doc)
      score = 0.0
      for t in tokens:
        if t not in self._df:
          continue
        f = tf.get(t, 0)
        idf = math.log((self._n - self._df[t] + 0.5) / (self._df[t] + 0.5) + 1.0)
        denom = f + self._k1 * (1 - self._b + self._b * self._doc_lens[i] / self._avgdl)
        score += idf * (f * (self._k1 + 1)) / denom
      if score > 0:
        scores.append((self._keys[i], score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]
