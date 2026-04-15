from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from harness.lms.tool import (
  FuncToolCallException,
  FuncToolSpec,
  StatelessFuncToolBase,
)

# Maximum lines per scope file before warning the agent to split/summarize.
_MAX_SCOPE_LINES = 200

_FRONTMATTER_TEMPLATE = """\
---
scope: {scope}
updated: {date}
---

"""


def _today() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _scope_to_path(base: Path, scope: str) -> Path:
  """Convert a scope string like ``shared/pass/instcombine`` to a file path.

  Raises :class:`FuncToolCallException` if the scope has fewer than 2 parts.
  """
  parts = scope.strip("/").split("/")
  if len(parts) < 2:
    raise FuncToolCallException(
      f"Scope must have at least two parts (e.g., 'shared/pass/instcombine'), got: {scope!r}"
    )
  return base / "/".join(parts[:-1]) / f"{parts[-1]}.md"


def _try_scope_to_path(base: Path, scope: str) -> Path | None:
  """Like :func:`_scope_to_path` but returns ``None`` for single-part scopes."""
  parts = scope.strip("/").split("/")
  if len(parts) < 2:
    return None
  return base / "/".join(parts[:-1]) / f"{parts[-1]}.md"


def _ensure_scope_file(path: Path, scope: str) -> Path:
  """Return *path*, creating parent dirs and frontmatter if it doesn't exist."""
  path.parent.mkdir(parents=True, exist_ok=True)
  if not path.exists():
    path.write_text(_FRONTMATTER_TEMPLATE.format(scope=scope, date=_today()))
  return path


def _update_frontmatter_date(text: str) -> str:
  """Replace the ``updated:`` field in YAML frontmatter with today's date."""
  return re.sub(
    r"^(updated:\s*).*$",
    rf"\g<1>{_today()}",
    text,
    count=1,
    flags=re.MULTILINE,
  )


def _extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
  """Extract simple keywords from *text* for dedup checking."""
  # Strip markdown formatting and common stop words.
  # TODO: Use a more robust NLP approach
  stop = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "and",
    "but",
    "or",
    "not",
    "if",
    "when",
    "then",
    "than",
    "so",
    "no",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "only",
    "same",
    "also",
    "just",
    "because",
    "about",
  }
  words = re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text)
  seen = set()
  keywords = []
  for w in words:
    low = w.lower()
    if low not in stop and low not in seen and len(low) > 2:
      seen.add(low)
      keywords.append(w)
      if len(keywords) >= max_keywords:
        break
  return keywords


def _term_matches(query_term: str, keyword: str) -> bool:
  """Bidirectional substring match (both sides already lowercase)."""
  return query_term in keyword or keyword in query_term


def _iter_scope_files(base_dir: Path, search_dir: Path) -> list[tuple[Path, str]]:
  """Yield ``(path, scope_string)`` for each ``.md`` file under *search_dir*."""
  return [
    (md, str(md.relative_to(base_dir).with_suffix("")))
    for md in sorted(search_dir.rglob("*.md"))
  ]


@dataclass
class _InsightEntry:
  """A single insight entry parsed from a scope file."""

  title: str
  body: str  # Full text including title
  keywords: list[str] = field(default_factory=list)  # From _Keywords: line
  scope: str = ""  # Scope derived from file path
  score: float = 0.0


def _parse_entries(text: str, scope: str) -> list[_InsightEntry]:
  """Split a scope file into individual insight entries on ``## `` headings."""
  entries: list[_InsightEntry] = []
  # Split on ## headings (keep the heading with its body).
  parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
  for part in parts:
    part = part.strip()
    if not part.startswith("## "):
      continue
    title_end = part.find("\n")
    title = part[3:title_end].strip() if title_end != -1 else part[3:].strip()
    kw_match = re.search(r"_Keywords:\s*(.+?)_", part)
    kw_list = []
    if kw_match:
      kw_list = [k.strip().lower() for k in kw_match.group(1).split(",") if k.strip()]
    entries.append(_InsightEntry(title=title, body=part, keywords=kw_list, scope=scope))
  return entries


def _collect_all_entries(base_dir: Path, scope: str | None) -> list[_InsightEntry]:
  """Collect all insight entries from files under a directory or scope."""
  entries: list[_InsightEntry] = []
  if scope:
    file_path = _try_scope_to_path(base_dir, scope)
    if file_path and file_path.exists():
      entries.extend(_parse_entries(file_path.read_text(), scope))
      return entries
    search_dir = base_dir / scope.strip("/")
    if search_dir.is_dir():
      for md, rel in _iter_scope_files(base_dir, search_dir):
        entries.extend(_parse_entries(md.read_text(), rel))
    return entries
  for md, rel in _iter_scope_files(base_dir, base_dir):
    entries.extend(_parse_entries(md.read_text(), rel))
  return entries


def _tokenize_query(query: str) -> list[str]:
  """Tokenize a search query into lowercase terms."""
  return [
    w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", query) if len(w) > 1
  ]


def _bm25_score(
  query_terms: list[str],
  entries: list[_InsightEntry],
  *,
  k1: float = 1.5,
  b: float = 0.75,
) -> list[_InsightEntry]:
  """Score entries against query terms using BM25 over the keywords field.

  Each entry's keywords list is the "document". The query terms are matched
  against it. Entries with no keywords get a small body-text fallback score.
  """
  if not entries or not query_terms:
    return []

  n = len(entries)
  avg_dl = sum(len(e.keywords) for e in entries) / max(n, 1) or 1.0

  # Single pass: compute per-entry tf maps and global df simultaneously.
  df: dict[str, int] = {}
  entry_tf: list[dict[str, int]] = []
  for entry in entries:
    tf_map: dict[str, int] = {}
    for kw in entry.keywords:
      for qt in query_terms:
        if _term_matches(qt, kw):
          tf_map[qt] = tf_map.get(qt, 0) + 1
    for qt in tf_map:
      df[qt] = df.get(qt, 0) + 1
    entry_tf.append(tf_map)

  for entry, tf_map in zip(entries, entry_tf):
    score = 0.0
    dl = len(entry.keywords) or 1
    for qt in query_terms:
      tf = tf_map.get(qt, 0)
      if tf == 0:
        continue
      idf = math.log((n - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1.0)
      tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
      score += idf * tf_norm
    if score == 0.0 and not entry.keywords:
      body_lower = entry.body.lower()
      body_hits = sum(1 for qt in query_terms if qt in body_lower)
      score = body_hits * 0.1
    entry.score = score

  return sorted([e for e in entries if e.score > 0], key=lambda e: -e.score)


class InsightTool(StatelessFuncToolBase):
  """Record, load, and search LLVM insights across runs.

  Insights are stored as Markdown files organized by scope under a base
  directory.  Each scope (e.g., ``shared/pass/instcombine``) maps to one
  file that may contain multiple insight entries.
  """

  def __init__(self, insight_dir: Path):
    self.insight_dir = Path(insight_dir).resolve()

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "insight",
      "Persistent LLVM insight store that survives across runs. "
      "Use this to save and recall knowledge (patterns, pitfalls, heuristics). "
      "Actions: list, record, load, keyword_search.",
      [
        FuncToolSpec.Param(
          "action",
          "string",
          True,
          "The action to perform: "
          "'list' — show available scopes with entry/line counts; "
          "'record' — save a new insight; "
          "'load' — retrieve all insights under a scope; "
          "'keyword_search' — BM25-ranked search over insight keywords.",
        ),
        FuncToolSpec.Param(
          "scope",
          "string",
          False,
          "Scope path, e.g., 'shared/pass/instcombine', 'task/autofix/strategies'. "
          "[list] optional — filter to scopes under this prefix. "
          "[record] REQUIRED — the scope to write the insight to. "
          "[load] REQUIRED — one or more comma-separated scope prefixes to load. "
          "[keyword_search] optional — narrow search to this scope.",
        ),
        FuncToolSpec.Param(
          "title",
          "string",
          False,
          "[record] REQUIRED — a short title for the insight entry, "
          "used as a Markdown heading in the scope file.",
        ),
        FuncToolSpec.Param(
          "text",
          "string",
          False,
          "[record] REQUIRED — the insight content. Should be a concise, "
          "generalizable observation — not specific line numbers or ephemeral "
          "details. Use Markdown formatting.",
        ),
        FuncToolSpec.Param(
          "keywords",
          "string",
          False,
          "[record] REQUIRED — comma-separated domain-specific keywords that "
          "make the insight findable via keyword_search. Choose terms an agent "
          "would search for, including ones not in the prose text "
          "(e.g., 'nsw, zext, instcombine, flag-propagation').",
        ),
        FuncToolSpec.Param(
          "source",
          "string",
          False,
          "[record] optional — provenance of the insight, e.g., 'issue #98234'.",
        ),
        FuncToolSpec.Param(
          "query",
          "string",
          False,
          "[keyword_search] REQUIRED — keywords or terms to search for.",
        ),
        FuncToolSpec.Param(
          "top_k",
          "integer",
          False,
          "[keyword_search] optional — maximum number of results to return "
          "(default: 10).",
        ),
      ],
      keywords=["insight", "knowledge", "store", "persistent", "llvm"],
    )

  def _call(
    self,
    *,
    action: str,
    scope: str = None,
    keywords: str = None,
    text: str = None,
    title: str = None,
    source: str = None,
    query: str = None,
    top_k: int = None,
    **kwargs,
  ) -> str:
    match action:
      case "list":
        return self._list(scope=scope)
      case "record":
        return self._record(
          scope=scope, keywords=keywords, text=text, title=title, source=source
        )
      case "load":
        return self._load(scope=scope)
      case "keyword_search":
        return self._keyword_search(query=query, scope=scope, top_k=top_k)
      case _:
        raise FuncToolCallException(
          f"Unknown action: {action!r}. "
          f"Use 'list', 'record', 'load', or 'keyword_search'."
        )

  # ------------------------------------------------------------------
  # list
  # ------------------------------------------------------------------

  def _list(self, *, scope: str | None) -> str:
    search_dir = self.insight_dir
    if scope:
      candidate = self.insight_dir / scope.strip("/")
      if not candidate.is_dir():
        return "No scopes found." + f" (filtered by: {scope})"
      search_dir = candidate

    scopes: list[str] = []
    for md, rel in _iter_scope_files(self.insight_dir, search_dir):
      content = md.read_text()
      line_count = content.count("\n")
      entry_count = len(_parse_entries(content, rel))
      scopes.append(f"  {rel}  ({entry_count} entries, {line_count} lines)")

    if not scopes:
      return "No scopes found." + (f" (filtered by: {scope})" if scope else "")

    header = f"Available scopes ({len(scopes)}):"
    if scope:
      header += f" (filtered by: {scope})"
    return header + "\n" + "\n".join(scopes)

  # ------------------------------------------------------------------
  # record
  # ------------------------------------------------------------------

  def _record(
    self,
    *,
    scope: str | None,
    keywords: str | None,
    text: str | None,
    title: str | None,
    source: str | None,
  ) -> str:
    if not scope:
      raise FuncToolCallException("'scope' is required for the 'record' action.")
    if not keywords:
      raise FuncToolCallException("'keywords' is required for the 'record' action.")
    if not text:
      raise FuncToolCallException("'text' is required for the 'record' action.")
    if not title:
      raise FuncToolCallException("'title' is required for the 'record' action.")

    path = _scope_to_path(self.insight_dir, scope)
    _ensure_scope_file(path, scope)

    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]

    # Dedup uses prose-extracted keywords (not agent-provided ones) — dedup asks
    # "is this the same insight?", while agent keywords ask "how do I find it?".
    existing = path.read_text()
    prose_keywords = _extract_keywords(text)
    if prose_keywords:
      existing_lower = existing.lower()
      hits = sum(1 for kw in prose_keywords if kw.lower() in existing_lower)
      overlap = hits / len(prose_keywords)
      if overlap > 0.8:
        return (
          f"Insight likely already covered in {scope}: "
          f"More than {overlap:.0%} words are contained in the scope. Skipped. "
          f"Use 'load' to review existing insights in this scope."
        )

    entry = f"\n## {title}\n\n{text.rstrip()}\n"
    if kw_list:
      entry += f"\n_Keywords: {', '.join(kw_list)}_\n"
    if source:
      entry += f"\n_Source: {source}_\n"

    content = _update_frontmatter_date(existing) + entry
    path.write_text(content)

    line_count = content.count("\n")
    warning = ""
    if line_count > _MAX_SCOPE_LINES:
      warning = (
        f" WARNING: scope file now has {line_count} lines "
        f"(recommended cap: {_MAX_SCOPE_LINES}). Consider splitting into "
        f"sub-scopes (e.g., '{scope}/subtopic') or summarizing older entries."
      )

    return f"Recorded insight in {scope}.{warning}"

  # ------------------------------------------------------------------
  # load
  # ------------------------------------------------------------------

  def _load(self, *, scope: str | None) -> str:
    if not scope:
      raise FuncToolCallException(
        "'scope' is required for the 'load' action. "
        "Provide one or more comma-separated scope prefixes, "
        "e.g., 'shared/pass/instcombine,task/autofix'."
      )

    scopes = [s.strip() for s in scope.split(",") if s.strip()]
    collected: list[str] = []

    for sc in scopes:
      sc = sc.strip("/")
      dir_path = self.insight_dir / sc
      if dir_path.is_dir():
        for md, rel in _iter_scope_files(self.insight_dir, dir_path):
          text = md.read_text().strip()
          if text:
            collected.append(f"<!-- scope: {rel} -->\n{text}")
      else:
        file_path = _try_scope_to_path(self.insight_dir, sc)
        if file_path and file_path.exists():
          text = file_path.read_text().strip()
          if text:
            collected.append(f"<!-- scope: {sc} -->\n{text}")

    if not collected:
      return f"No insights found for scope(s): {scope}"
    return "\n\n".join(collected)

  # ------------------------------------------------------------------
  # keyword_search
  # ------------------------------------------------------------------

  _DEFAULT_TOP_K = 10

  def _keyword_search(
    self, *, query: str | None, scope: str | None, top_k: int | None
  ) -> str:
    if not query:
      raise FuncToolCallException(
        "'query' is required for the 'keyword_search' action."
      )

    k = top_k if top_k is not None else self._DEFAULT_TOP_K

    query_terms = _tokenize_query(query)
    if not query_terms:
      raise FuncToolCallException(
        f"Could not extract any search terms from query: {query!r}"
      )

    entries = _collect_all_entries(self.insight_dir, scope)
    if not entries:
      return f"No insights found in scope: {scope or '(all)'}"

    # Score and rank entries by BM25 over their keywords.
    ranked = _bm25_score(query_terms, entries)
    if not ranked:
      return f"No insights found matching: {query}"

    # Return top K results.
    top = ranked[:k]
    parts: list[str] = []
    parts.append(
      f"Found {len(ranked)} matching insight(s) for: {query} (showing top {len(top)})\n"
    )
    for i, entry in enumerate(top, 1):
      parts.append(
        f"--- [{i}] scope: {entry.scope} | "
        f"score: {entry.score:.2f} | "
        f"keywords: {', '.join(entry.keywords) or '(none)'} ---"
      )
      parts.append(entry.body.strip())
      parts.append("")  # blank line between entries

    return "\n".join(parts)
