"""Text processing utilities — keyword extraction, tokenization, matching."""

import re

# ---------------------------------------------------------------------------
# Stop words
# ---------------------------------------------------------------------------

STOP_WORDS = frozenset({
  "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
  "have", "has", "had", "do", "does", "did", "will", "would", "could",
  "should", "may", "might", "shall", "can", "to", "of", "in", "for",
  "on", "with", "at", "by", "from", "as", "into", "through", "during",
  "before", "after", "it", "its", "this", "that", "these", "those",
  "and", "but", "or", "not", "if", "when", "then", "than", "so", "no",
  "all", "each", "every", "both", "few", "more", "most", "other", "some",
  "such", "only", "same", "also", "just", "because", "about",
})  # fmt: skip


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------


def extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
  """Extract unique, non-stop-word keywords from *text*.

  Returns up to *max_keywords* words in order of first appearance.
  Words shorter than 3 characters are skipped.
  """
  words = re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text)
  seen: set[str] = set()
  keywords: list[str] = []
  for w in words:
    low = w.lower()
    if low not in STOP_WORDS and low not in seen and len(low) > 2:
      seen.add(low)
      keywords.append(w)
      if len(keywords) >= max_keywords:
        break
  return keywords


# ---------------------------------------------------------------------------
# Query tokenization
# ---------------------------------------------------------------------------


def tokenize_query(query: str) -> list[str]:
  """Tokenize a search query into lowercase terms.

  Accepts identifiers with hyphens and underscores (e.g., ``flag-propagation``,
  ``inst_combine``). Single-character tokens are dropped.
  """
  return [
    w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", query) if len(w) > 1
  ]


# ---------------------------------------------------------------------------
# Term matching
# ---------------------------------------------------------------------------


def either_contains(query_term: str, keyword: str) -> bool:
  """True if either string contains the other (both sides assumed lowercase)."""
  return query_term in keyword or keyword in query_term
