# Insight System

## Overview

The insight system provides persistent, cross-run memory for LLVM agents. Instead
of starting from zero every run, agents accumulate knowledge about passes, patterns,
debugging heuristics, and repair strategies. This knowledge is shared across agent
types (autofix, autoreview, superopt, etc.) and across users.

The unit of stored knowledge is called an **insight**. The tool is called
**InsightTool**.

## Goals

- Agents get progressively better as insights accumulate
- Shared insights benefit all task types and all users
- Zero new infrastructure -- files + ripgrep + git
- Git-trackable, reviewable, diffable
- Fits the existing harness tool/skill architecture

## Storage Format

### Why files, not a database?

- Git-trackable -- version, diff, and review knowledge changes
- No extra infrastructure (no SQLite, no vector DB, no embedding model)
- Existing tools (ripgrep, glob) work for search
- Aligns with harness design principle: "the harness is infrastructure, not a framework"

NoSQL or vector DB may be considered later if the volume exceeds ~10K entries.

### File granularity

One file per scope, multiple insights per file. Each scope file (e.g.,
`instcombine.md`) is a living document. Insights are appended as sections.

- Keeps file count manageable
- Makes `load` trivial -- just read the file
- The model can reorganize the file over time

Cap: ~200 lines / ~4K tokens per scope file. When a file exceeds this, the
recording mechanism should summarize/compress older entries or split into sub-scopes.

### File structure

Minimal enforced frontmatter, free-form body. The model structures the body however
it thinks is clearest.

```markdown
---
scope: shared/pass/instcombine
updated: 2026-04-06
contributors: 3
---

# InstCombine Insights

## nsw/nuw flag propagation in sext(zext(x)) folds

When InstCombine folds sext(zext(x)) into a single extend, the nsw and nuw
flags must be intersected, not unioned. The outer sext's nsw does not imply
the combined operation preserves nsw.

Source: issue #98234, #101456

## Constant folding with poison values
...
```

Why not enforce more structure? Because insight types are unpredictable. Some are
"don't do X." Some are "when you see pattern Y, the root cause is usually Z." Some
are debugging heuristics. Forcing these into a rigid schema fights the model's
strength -- clear prose explanation of nuanced knowledge.

## Directory Layout

```
insight/
  shared/                    # git-tracked, curated, high-signal
    pass/                    # pass-specific knowledge
      instcombine.md
      simplifycfg.md
      ...
    middle-end/              # broader middle-end patterns
    backend/                 # backend-specific patterns
    debugger/                # GDB/debugging heuristics
    ir-patterns/             # common IR idiom knowledge
  task/                      # task-specific knowledge
    autofix/                 # bug-fixing strategies
    autoreview/              # patch review patterns
    superopt/                # future: superoptimization
  local/                     # gitignored, per-user, raw
    ...                      # same sub-structure as shared/
```

`insight/local/` is `.gitignored` from day one. Only `insight/shared/` and
`insight/task/` are tracked.

## Operations

### list

Show available scopes with entry counts and line counts. Helps agents discover
what's in the store before searching or loading.

- Called by: the agent (typically at task start or when exploring)
- Parameters: scope (optional filter prefix)
- Behavior: scans all `.md` files under the insight directory (or filtered prefix),
  reports each scope with its entry count and line count

### record

Write a new insight or append to an existing scope file.

- Called by: the agent itself (mid-task or end-of-task), or a post-processing
  curation skill
- Parameters: scope, tags, text, source (optional provenance)
- Behavior: check for dedup before writing; append to scope file or create it

### load

Return all insights matching a scope filter. Used at task start to inject relevant
context.

- Called by: agent setup code or the agent itself
- Parameters: list of scope prefixes
- Behavior: read and concatenate matching scope files
- Budget: cap total loaded tokens (~4K per scope, select scopes carefully)

### keyword_search

Find insights matching query terms. Fast, deterministic, zero cost.

- Called by: the agent
- Parameters: query (keywords), scope (optional filter), top_k (optional, default 10)
- Behavior: tokenizes the query, scores all entries by BM25 over their `_Keywords:`
  fields (with bidirectional substring matching), returns top K entries ranked by
  relevance. Entries without keywords get a small body-text fallback score.

### semantic_search (via llvm-insight-search skill)

Answer a natural language question by searching and synthesizing insights.
Implemented as a skill (`harness/skills/llvm-insight-search/SKILL.md`), not a
tool action — this keeps InsightTool decoupled from the agent framework.

- Called by: the agent (when keyword_search is too narrow or returns noise)
- Parameters: query (natural language question), scope (optional filter)
- Behavior: skill sub-agent uses `insight` (list/load/keyword_search), `read`,
  and `ripgrep` to find and synthesize relevant insights
- Cost: one skill call (~500-2K tokens)

## Quality Gate -- What's Worth Saving?

Three levels of filtering, applied in order:

### Level 1: Agent-side heuristics (at record time)

The agent should only record when something meets a surprise threshold:

- It contradicts what the agent initially expected
- It required many tool calls to discover (high cost = high value)
- It's a pattern that applies beyond the current bug (generalizable)
- It corrects a mistake the agent made during the run

Encoded in prompts: "only record insights that would help a future agent avoid the
same dead end or reach the fix faster."

### Level 2: Dedup check (at record time)

Before writing, search for similar content in the target scope. If existing content
covers >80% of the same ground (by keyword overlap), skip or merge instead of
duplicating.

```python
def record(self, scope, text, ...):
    existing = self._search_scope(scope, extract_keywords(text))
    if existing and is_redundant(text, existing):
        return "Insight already covered. Skipped."
    # else append
```

### Level 3: Post-run curation (the quality gate that matters most)

A curation skill that:

1. Takes the agent's raw recorded insights from a run (in `local/`)
2. Evaluates each against criteria:
   - Did the fix actually work? Only promote insights from successful runs.
   - Is it generalizable? "Line 1423 had a bug" is useless. "InstCombine doesn't
     check for poison when folding X" is valuable.
   - Is it novel? Check against existing shared insights.
3. Outputs refined insights to `insight/shared/` (or proposes them as a PR)

## Multi-User Model

### Two tiers

| Tier | Location | Tracked? | Content |
|------|----------|----------|---------|
| Local | `insight/local/` | gitignored | Raw agent recordings, hypotheses, failed-run notes |
| Shared | `insight/shared/` | git-tracked | Curated, validated, from successful runs |

### Promotion pipeline

```
Agent run
  -> raw insights recorded to insight/local/
  -> fix succeeds? Run curation skill
    -> curated insights proposed to insight/shared/
    -> submitted as PR (or appended for batch review)
```

Users record whatever they want locally. Promotion to shared is gated by curation.
A maintainer (or automated review agent) merges the PR.

## Search Design

### keyword_search (baseline, always available)

- Deterministic, fast, zero cost
- BM25-ranked: tokenizes query, scores entries by keyword overlap, returns top K
- Bidirectional substring matching: "nsw" matches keyword "nsw-flag" and vice versa
- Entries without keywords get a body-text fallback (lower weight)
- Works well when the agent knows what to search for: a pass name, an instruction
  pattern, a keyword like "nsw" or "poison"

### semantic_search (llvm-insight-search skill)

- Implemented as a harness skill, not a tool action — clean separation
- Skill sub-agent uses `insight` (list/load/keyword_search), `read`, and `ripgrep`
- Works in any agent or sub-agent that has the skill registered — no special binding
- Cost: one skill call (~500-2K tokens)
- Use when keyword_search returns noise or when the question is conceptual
  (e.g., "What are common pitfalls when folding binary operators?")

### Embeddings (deferred)

- Not justified at current expected volume (hundreds of insights)
- Keyword search + agent reasoning covers the semantic gap
- Revisit if the insight store exceeds ~10K entries

## Curation Skill (llvm-insight-reflect)

The `llvm-insight-reflect` skill (`harness/skills/llvm-insight-reflect/SKILL.md`)
is a post-run curation agent that promotes worthy insights from `local/` to
`shared/`. It runs automatically after a successful fix in `autofix/mini.py`.

The skill:
1. Loads raw insights from `insight/local/`
2. Evaluates each for generalizability, novelty, and clarity
3. Promotes worthy insights to the appropriate shared scope via `insight record`
4. Reports what was promoted and what was skipped

The skill runs in a forked context (`context: fork`) so it doesn't pollute the
main agent's conversation history. It has access to `read`, `ripgrep`, and
`insight` tools.

## Architectural Fit

The InsightTool is a **stateless harness tool** -- like ReadTool or RipgrepTool. It
operates on the `insight/` data directory. It has no dependency on agents, configs,
or the agent framework.

Per established design principles:
- Harness provides `make_tools()` / `make_tool("insight")` -- agent code handles
  registration and budgets
- Agent-specific recording logic (what to record, when) stays in agent code
- Semantic search and curation are harness **skills** under `harness/skills/`,
  not tool actions -- this keeps InsightTool decoupled from the agent framework
  and ensures sub-agents inherit the same capabilities via skill registration

## Pros and Cons

### Pros

- Zero new infrastructure
- Git-trackable, reviewable, diffable
- Scope hierarchy is intuitive and extensible
- Agents improve over time as insights accumulate
- Shared insights benefit all task types
- Fits existing tool/skill architecture

### Cons

- Text-based search is keyword-dependent
- No semantic similarity without embeddings
- Context window cost from loading insights
- Quality depends on recording agent/skill quality
- Risk of stale/wrong insights misleading agents (needs maintenance)
- No structured querying (e.g., "all insights about nsw from the last month")
