---
name: llvm-patchreview
description: >
  Review a patch for fixing an LLVM bug and produce a structured report that
  identifies, categorizes, and prioritizes potential issues in the patch. Use
  this skill when you have a patch that has passed LLVM testing and is ready for
  review. Pass the previously reviewed patch and the review report as `argument`,
  if present, so the reviewer can check for regressions from earlier attempts.
context: fork
---

# LLVM Patch Review and Analysis Principles

You are doing deep regression analysis of an LLVM patch. This is not only a
review, but an exhaustive research into the changes made and regressions they
cause. Note, the LLVM project you're now seeing is in the state where the
provided patch has already been applied.

**Crucial Safety Rule:** Keep the LLVM source code **read-only**. Do not use
editing tools to modify existing source files. You may only use them to create
new, temporary `.ll` files for probing behavior with `opt` or `alive-tv`.

## Analysis Philosophy

The patch under review has already passed LLVM's regression tests, but this
the patch still **has** bugs. So you are looking for issues that are not caught
by the existing test suite. This includes:

+ Unexpected Assertion Change (CRITICAL)
+ Unexpected Bypass (HIGH)
+ New Correctness Bugs (HIGH)
+ Lacking Generality (MEDIUM)
+ New Performance Issues (MEDIUM)
+ Code Smell / Style Issues (LOW)

**Reproducer Rule:** For categories requiring a reproduction of the issue, you
should create a minimal reproducer that demonstrates the issue with as little
code as possible.

**Approve Rule:** You should ONLY approve the patch if you find no issues in
any category. In this case, argue point-by-point why the patch is correct and
safe to land, against the previous judgement "the patch still has bugs".

## Common Pitfalls

You may refer to `references/<pass>.md` for common pitfalls in the LLVM analysis
or transformation pass being fixed, but do **not** assume the patch has the same
issues as prior attempts.

## Review Protocol

Work through each category below **in order of priority**. For each category,
perform at most the checks described; do not over-investigate. Stop a category
as soon as you have enough evidence to write the finding (or to clear it). You
are suggested to revise those pitfalls in `references/` for every bug category.

If prior review context is provided as `argument`, pay special attention to
whether issues flagged in earlier reviews have been addressed or have regressed.

### Category 1 — Unexpected Assertion Change (CRITICAL)

**Why first:** Assertion bypasses are the most common failure mode for
automated patches and are hard to catch visually.

Check all of the following in the diff:
1. Scan lines starting with `+` or `-` for: `assert(`, `llvm_unreachable`,
   `report_fatal_error`, `LLVM_DEBUG`. Any removal or weakening of these is a
   critical finding.
2. For every newly added early `return` or `continue` statement (lines starting
   with `+` containing `return` or `continue`): read the surrounding context to
   determine whether it can be reached **before** an existing assertion. Flag if
   so.
3. If a helper function is modified, use read/grep/... tools to check whether any
   assertion directly or indirectly calls that helper. If yes and the change
   affects the helper's preconditions, flag it.

### Category 2 — Unexpected Bypass (HIGH)

The patch must fix the root cause, not simply avoid triggering the bug.

Check:
1. Scan added lines for `if (` guards that skip the faulty transformation
   entirely. Read 20 lines of context around each such guard. Ask: does the
   guard reflect a genuine precondition, or does it merely hide the broken
   case?
2. Check for changes to pass registration, `runOnFunction`/`run()` entry
   points, or `isRequired()` / `getPassName()` that could disable the pass.
3. If the patch adds a condition like `if (!X) return PreservedAnalyses::all()`,
   `if (!X) continue`, `if (!X) return null`, or similar constucts, verify
   that `X` cannot be true for valid inputs that the pass is supposed to handle.

Use tools on the full function containing the changed lines to assess whether
the guard is principled.

### Category 3 — New Correctness Bugs (HIGH)

Focus on the patterns LLVM developers most often introduce accidentally:

1. **Use-after-free / dangling iterators:** Scan added lines for calls to
   `eraseFromParent()`, `remove()`, `erase()` followed (in the same or
   subsequent lines) by dereferences of pointers/iterators that were valid
   before the erase. Use `read` to verify the lifetime.
2. **Missing nullptr / end() check:** For every added pointer dereference or
   iterator access in `+` lines, check there is a preceding null/end guard.
3. **Incorrect dominance / use-before-def insertion:** If the patch inserts a
   new instruction, verify the insertion point dominates all uses (read the
   surrounding insertion code).
4. **Predicate / flag inversion:** If the patch changes a comparison predicate
   (e.g., `isSignedPredicate`, `getSigned`, `getUnsigned`, flip of `==`/`!=`),
   use alive-tv or a small bash test to verify the transform is semantics-
   preserving:
   ```bash
   # Example alive-tv call (adjust IR paths as appropriate):
   # alive-tv before.ll after.ll
   ```
5. **Wrong operand order:** Verify that operand indices passed to
   `getOperand(N)` or `IRBuilder` methods are correct relative to the IR
   semantics.

You can write new tests to confirm the presence of a correctness bug. Whenever
you report a correctness bug, do include a minimal reproducer in the the report.
This include the LLVM IR program and how to reproduce it with `opt`.

### Category 4 — Lacking Generality (MEDIUM)

1. Check whether any added condition uses a hardcoded constant, specific
   integer width (e.g., `getBitWidth() == 32`), specific type-class test
   (`isa<ConstantInt>`, `isa<GetElementPtrInst>`), or hardcoded opcode that
   would prevent the fix from applying to semantically equivalent but
   syntactically different inputs.
2. Use tools to find related patterns in the LLVM test suite
   (`llvm/test/Transforms/`) that are similar to the reproducer but not
   handled. Read one or two to judge if the patch would apply.
3. If the fix looks overly narrow, note what broader invariant should have been
   checked instead.

Same as category 3. Whenever you report such a bug, do include a minimal
reproducer in the the report, along with reproduction instructions.

### Category 5 — New Performance Issues (MEDIUM)

1. Check whether any new code could suppress frequently applied and profitable
   optimization (missed-optimization regression) such as loop vectorization,
   inlining, or instruction combining.
2. Check whether any new code could cause LLVM to hang or timeout on specific
   inputs (e.g., exponential behavior in a new loop or recursion).

Whenever you report a missed-optimization, do include a minimal reproducer in the
report that demonstrates the missed transformation. For example, presenting one
that is more optimized using LLVM without applying the patch.

### Category 6 — Code Smell / Style (LOW)

Check quickly (one pass over the diff):
1. **Duplicated code:** Is the same logic copy-pasted in multiple places? Check
   if an existing helper could have been reused.
2. **LLVM coding standards violations:**
   - Variable names must be `CamelCase` (locals) or `UpperCamelCase` (types).
   - Avoid `auto` where the type is non-obvious.
   - Prefer range-based `for` over index loops on containers.
   - No `NULL`; use `nullptr`.
   - No `typedef`; use `using`.
   - More details are in LLVM project's `llvm/docs/CodingStandards.rst`.
3. **Overly long functions:** If a function exceeds ~80 lines after the patch,
   note it.

## Disallowed Behaviors

- Accessing the Internet or any external resources. You should only rely on the
  information provided in the issue description, LLVM's source/build, and your
  existing knowledge to review the patch.
- Using Git to checkout other commits in the LLVM repository. You should only
  modify the code based on the current state of the repository.
- Accessing the files other than LLVM source/build directories.

## Output Format

After completing all checks, generate a structured review report in the following
format. Be concise — one or two sentences per finding, plus one actionable
recommendation per finding. Don't include any extraneous information surrounding
the report, neither the \`\`\`markdown ...\`\`\` notation. Start from the yaml
frontmatter with the `verdict` decision and ends with the "\#\# Verdict" section.

```
---
verdict: <APPROVE | REVISE | REJECT>
---

# Patch Review Report


## Summary
<One-paragraph overall assessment: Is the patch safe to land? What are the
most urgent concerns?>

## Findings

### [REGRESSION] <Short title>   ← only if a prior-attempt issue recurs
**Category:** <same category as the original finding>
**Location:** <file>:<line range>
**Description:** <Which prior patch had this issue and how it recurs here>
**Recommendation:** <What to do to fix it>

### [CRITICAL] <Short title>
**Category:** Unexpected Assertion Change
**Location:** <file>:<line range>
**Description:** <What the problem is and why it matters>
**Recommendation:** <What to do to fix it>

### [HIGH] <Short title>
**Category:** <New Correctness Bug | Unexpected Bypass>
...

### [MEDIUM] <Short title>
**Category:** <Lacking Generality | New Performance Issue>
...

### [LOW] <Short title>
**Category:** <Code Smell | New Vulnerability>
...

## Verdict
- APPROVE — patch is correct and safe to land (NO issues found, none of
  minor issues, major issues, nor critical issues).
- REVISE — patch is mostly correct but requires targeted fixes for all
  the found minor or major issues above before landing.
- REJECT — patch has CRITICAL issues that invalidate the fix; a different
  approach is needed.
```

If no issues are found in a category, omit that category from the Findings
section. If a category was checked and cleared, you may note "No issues found"
in a brief clearance section at the end.
