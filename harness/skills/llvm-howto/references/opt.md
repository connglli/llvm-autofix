# opt — LLVM Optimizer

`opt` reads LLVM IR, applies optimization passes, and writes the result.

## Pass Pipeline Syntax

```bash
# Single pass
opt -passes=instcombine -S input.ll

# Multiple passes (comma-separated)
opt -passes='instcombine,simplifycfg,gvn' -S input.ll

# Explicit pass manager nesting
opt -passes='function(instcombine,simplifycfg)' -S input.ll

# Module-level pass wrapping function passes
opt -passes='module(function(instcombine))' -S input.ll

# Loop passes
opt -passes='function(loop(licm,loop-unroll))' -S input.ll
```

## Useful Flags

| Flag | Description |
|------|-------------|
| `-S` | Emit human-readable IR (instead of bitcode) |
| `-o <file>` | Write output to file (default: stdout) |
| `-debug` | Enable all debug output (very verbose) |
| `-debug-only=<type>` | Enable debug output for specific DEBUG_TYPE |
| `-print-after-all` | Print IR after every pass |
| `-print-before=<pass>` | Print IR before a specific pass |
| `-print-after=<pass>` | Print IR after a specific pass |
| `-stats` | Print pass statistics |
| `-time-passes` | Time each pass |
| `-verify-each` | Run the IR verifier after every pass |
| `--disable-output` | Don't write output IR (useful with -print-* flags) |

## Debug Output

To get debug output from a pass, you need:
1. LLVM built with assertions (`LLVM_ENABLE_ASSERTIONS=ON`)
2. The pass's `DEBUG_TYPE` string (found via `grep '#define DEBUG_TYPE' <pass>.cpp`)

```bash
opt -passes=instcombine -S -debug-only=instcombine input.ll 2>log.txt
```

Multiple debug types:

```bash
opt -passes=gvn -S -debug-only=gvn,memdep input.ll 2>log.txt
```

## Common Pass Names

### Scalar / Instruction-Level

| Pass | Description |
|------|-------------|
| `instcombine` | Combine instructions into fewer, simpler forms (algebraic identities, strength reduction, dead operand folding). Does not modify CFG. |
| `aggressive-instcombine` | More aggressive expression pattern combining that may introduce new instructions (e.g., truncation sinking). |
| `simplifycfg` | Simplify and canonicalize the CFG: merge blocks, eliminate unreachable code, convert switches to branches, sink common code. |
| `gvn` | Global Value Numbering — eliminate fully redundant loads and instructions, partial redundancy elimination. |
| `newgvn` | Modern GVN implementation using value elimination instead of value generation. More powerful but experimental. |
| `gvn-hoist` | Hoist similar expressions to common dominators using inverted value numbering. |
| `early-cse` | Early Common Subexpression Elimination — fast local CSE run early in the pipeline. |
| `sccp` | Sparse Conditional Constant Propagation — propagates constants through the function, removing dead branches. |
| `ipsccp` | Interprocedural SCCP — propagates constants across function boundaries (module pass). |
| `dse` | Dead Store Elimination — remove stores whose values are never read. |
| `dce` | Dead Code Elimination — remove instructions whose results are unused. |
| `adce` | Aggressive Dead Code Elimination — treats branches as dead unless proven live, removes more dead code than `dce`. |
| `bdce` | Bit-tracking Dead Code Elimination — removes dead bits from instructions using demanded-bits analysis. |
| `mem2reg` | Promote `alloca` instructions to SSA registers where possible (the classic SSA construction pass). |
| `sroa` | Scalar Replacement of Aggregates — break up `alloca` of structs/arrays into individual SSA values. Subsumes `mem2reg`. |
| `reassociate` | Reassociate commutative/associative expressions to expose constant folding and CSE opportunities. |
| `nary-reassociate` | Reassociate n-ary add/mul expressions to reuse already-computed sub-expressions. |
| `jump-threading` | Thread control flow through blocks with known branch conditions, duplicating blocks to eliminate branches. |
| `correlated-propagation` | Use lazy value info (LVI) to propagate value constraints (e.g., range info from comparisons) within a function. |
| `constraint-elimination` | Use known constraints (from assumes, dominating conditions) to eliminate redundant comparisons and checks. |
| `memcpyopt` | Optimize memcpy/memmove/memset calls: merge adjacent stores into memset, forward memcpy results. |
| `mergeicmps` | Merge chains of integer comparisons (e.g., manual struct equality) into a single memcmp call. |
| `tailcallelim` | Transform tail-recursive calls into loops. Also handles accumulator-style recursion (add/mul). |
| `flatten-cfg` | Flatten the CFG by converting if-then-else diamonds into select instructions where profitable. |
| `canon-freeze` | Canonicalize `freeze` instructions in loops to enable better optimization. |

### Loop Optimization

| Pass | Description |
|------|-------------|
| `licm` | Loop Invariant Code Motion — hoist/sink instructions that don't change across iterations out of the loop. |
| `indvars` | Induction Variable Simplification — canonicalize and simplify loop induction variables and trip counts. |
| `loop-unroll` | Unroll loops by duplicating the body to reduce branch overhead and expose optimization. |
| `loop-unroll-and-jam` | Unroll an outer loop and fuse (jam) the copies with the inner loop to improve locality. |
| `loop-rotate` | Rotate loops so the latch (back-edge) block is a conditional branch, enabling better optimization. |
| `loop-simplify` | Canonicalize loops: ensure a single preheader, dedicated exit blocks, and a single back-edge. |
| `lcssa` | Loop-Closed SSA — insert phi nodes at loop exits so defs inside the loop have a single use point outside. |
| `loop-delete` | Delete loops proven to have no observable side effects (dead loops). |
| `loop-distribute` | Split a loop with dependence cycles into multiple loops to enable vectorization of the independent parts. |
| `loop-flatten` | Collapse nested loops with linear iteration into a single loop (e.g., `for i for j` → `for ij`). |
| `loop-fusion` | Fuse adjacent loops with the same trip count and compatible control flow into a single loop. |
| `loop-idiom` | Recognize loop patterns (e.g., memset, memcpy, popcount) and replace them with library calls or intrinsics. |
| `loop-interchange` | Swap the order of nested loops to improve cache locality (e.g., column-major → row-major). |
| `loop-load-elim` | Forward loaded values across loop iterations to eliminate redundant loads at the cost of a phi node. |
| `loop-predication` | Widen loop-variant range checks into a single pre-loop check, removing checks from the hot path. |
| `loop-reduce` | Loop Strength Reduction (LSR) — replace expensive induction expressions (multiply) with cheaper ones (add). |
| `loop-simplifycfg` | Basic CFG simplification within a loop body to help other loop passes. |
| `loop-sink` | Sink instructions from the loop preheader into the loop body guided by profile data (cold path sinking). |
| `loop-term-fold` | Fold loop termination conditions to simplify exit logic. |
| `loop-versioning` | Create runtime-checked loop versions: a fast path assuming no aliasing and a safe fallback. |
| `loop-versioning-licm` | Combine loop versioning with LICM to hoist loads/stores that may alias behind a runtime check. |
| `simple-loop-unswitch` | Hoist loop-invariant conditions out of the loop, creating separate loops for each branch. |
| `irce` | Inductive Range Check Elimination — remove bounds checks proven safe for the loop's induction range. |

### Vectorization

| Pass | Description |
|------|-------------|
| `loop-vectorize` | Auto-vectorize innermost loops using SIMD instructions. Handles reductions, inductions, and if-conversion. |
| `slp-vectorizer` | Superword-Level Parallelism — vectorize straight-line code by packing independent scalar ops into vector ops. |
| `load-store-vectorizer` | Merge adjacent scalar loads/stores into vector loads/stores (primarily useful for GPU targets). |

### Interprocedural (Module/CGSCC)

| Pass | Description |
|------|-------------|
| `inline` | Inline function calls into callers when profitable (CGSCC pass, respects cost model). |
| `deadargelim` | Remove function arguments and return values that are never used by any caller. |
| `globalopt` | Optimize global variables: internalize, constant-propagate, shrink, or eliminate unused globals. |
| `globaldce` | Remove unreachable global variables and functions (global dead code elimination). |
| `argpromotion` | Promote by-reference arguments to by-value when the callee only reads a small amount of data. |
| `called-value-propagation` | Propagate function pointers at call sites for devirtualization opportunities. |
| `coro-elide` | Replace heap-allocated coroutine frames with stack allocations when the lifetime is provably bounded. |

## Predefined Pipelines

```bash
opt -O0 -S input.ll    # No optimization
opt -O1 -S input.ll    # Light optimization
opt -O2 -S input.ll    # Standard optimization
opt -O3 -S input.ll    # Aggressive optimization
opt -Os -S input.ll    # Size optimization
opt -Oz -S input.ll    # Aggressive size optimization
```
