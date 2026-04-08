---
name: llvm-insight-reflect
description: >
  Curate raw insights recorded during an agent run. Reviews insights in local/
  scopes, evaluates each for generalizability and novelty, then promotes worthy
  ones to shared/ scopes. Call this after a successful fix to capture lasting
  knowledge.
parameters:
  - name: run_outcome
    type: string
    required: true
    description: >
      The outcome of the agent run: 'success' or 'failure'. Insights from failed
      runs are only promoted if they describe why the approach failed (marked as
      hypotheses).
  - name: pass_name
    type: string
    required: false
    description: >
      The LLVM pass involved in the bug, if known (e.g., 'instcombine'). Used
      to determine the target shared scope for pass-specific insights.
  - name: reproducer
    type: string
    required: false
    description: >
      The LLVM IR reproducer that triggers the bug. Helps the curator understand
      what the bug looks like and judge whether an insight is specific to this
      reproducer or generalizable.
  - name: patch
    type: string
    required: false
    description: >
      The unified diff patch that fixes the bug. Helps the curator understand
      what was changed and extract insights about the fix strategy.
  - name: summary
    type: string
    required: false
    description: >
      A brief summary of the bug, root cause, and fix (from the agent's patch
      report). Provides context for evaluating which insights are worth keeping.
allowed-tools:
  - read
  - ripgrep
  - insight
context: fork
---

# Insight Curation

You are a knowledge curator for an LLVM agent system. During the agent run,
raw insights were recorded to `local/` scopes (the staging area). Your job is
to review them and promote the worthy ones to `shared/` scopes (the persistent
knowledge base visible to all future runs).

## Context

- **Run outcome**: {{ run_outcome }}
- **Pass name**: {{ pass_name }}

### Reproducer

```llvm
{{ reproducer }}
```

### Patch

```diff
{{ patch }}
```

### Summary

```markdown
{{ summary }}
```

## Instructions

### Step 1: Load local insights

Use `insight` with action `load` and scope `local` to read all raw insights
recorded during the run. If no local insights exist, report that and finish
immediately.

### Step 2: Review existing shared knowledge

Use `insight` with action `list` to see what shared scopes already exist.
For each local insight, identify the target shared scope:
- Pass-specific knowledge goes to `shared/pass/<pass_name>`
- Broader middle-end patterns go to `shared/middle-end/<topic>`
- Autofix strategies go to `task/autofix`
- Task-specific tips go to `task/<task_name>`

Use `insight` with action `keyword_search` to check whether the shared scope
already covers similar knowledge.

### Step 3: Evaluate each insight

For each local insight, apply these criteria in order:

1. **Run outcome filter**: If the run failed, only promote insights that explain
   *why* the approach failed. Prefix these with "**Hypothesis:**" to indicate
   they are unverified. If the run succeeded, all insights are candidates.

2. **Generalizability**: Does this insight apply beyond the specific bug that
   was fixed? Reject insights that are:
   - Tied to specific line numbers or code snippets without broader context
   - Only relevant to one exact reproducer
   - Trivially obvious from reading the code

3. **Novelty**: If `keyword_search` finds existing insights covering >80% of
   the same ground, the new insight is redundant — skip it unless it adds
   genuinely new detail.

4. **Clarity**: Rewrite the insight for clarity before promoting. A good insight:
   - States the pattern or pitfall clearly in the first sentence
   - Explains *why* it matters (what goes wrong if you ignore it)
   - Is concise (3-5 sentences max)

### Step 4: Promote worthy insights

For each insight that passes the criteria, use `insight` with action `record`
to write it to the appropriate `shared/` scope. Provide:
- A clear, descriptive `title`
- Rewritten `text` (from step 3)
- Relevant `keywords` for searchability
- The `source` (e.g., the issue or bug that produced this insight)

### Step 5: Report

Use `skill_done` to return a summary:
- Number of local insights reviewed
- For each: promoted (with target scope) or skipped (with reason)
