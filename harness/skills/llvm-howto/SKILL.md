---
name: llvm-howto
description: >
  Look up how to use LLVM command-line tools and utilities from the build
  directory, as well as where to find useful LLVM materials. Use this when
  you need to know which binary to run, what flags to pass, or how to
  interpret output from opt, llc, lli, llvm-lit, alive-tv, and other LLVM
  tools — even if the user just says "run the tests" or "check if this is
  correct" without naming a specific tool. Use this when you need to find
  more details about a specific LLVM entity (e.g. a pass name, a debug
  flag, a FileCheck directive) or when you need to find documentation on a
  specific topic (e.g. IR semantics, pass design, loop terminology).
---

# LLVM Tools Quick Reference

All binaries are located in the LLVM build directory under `bin/`.
Run `ls bin/` in the build directory to see every available binary.

## Which Tool?

| I want to... | Use |
|--------------|-----|
| Apply an optimization pass to IR | `opt` |
| Check if a pass crashes on an input | `opt` (check exit code) |
| See debug output from a pass | `opt -debug-only=<type>` |
| Verify a transformation is semantically correct | `alive-tv` |
| Confirm a miscompilation by running IR | `lli` |
| Compare IR before/after a change | `llvm-diff` |
| Compile IR to assembly | `llc` |
| Run regression tests | `llvm-lit` |
| Run a single test file | `llvm-lit <file>` |
| Reduce an IR test case to a minimal reproducer | `llvm-reduce` |
| Extract one function from a module | `llvm-extract` |
| Convert between .ll and .bc formats | `llvm-as` / `llvm-dis` |
| Understand an IR instruction's semantics | Read `llvm/docs/LangRef.rst` |
| Find which pass does what | Read `llvm/docs/Passes.rst` |

## Frequently Used Tools

| Binary | Purpose | Common Usage |
|--------|---------|--------------|
| `opt` | Run optimization passes on LLVM IR | `opt -passes=instcombine -S input.ll` |
| `llc` | Compile IR to target assembly or object code | `llc -O2 input.ll -o output.s` |
| `lli` | Interpret or JIT-compile and run IR | `lli input.ll` |
| `llubi` | Interpret run IR strictly following LLVM IR's semantics | `llubi input.ll` |
| `llvm-lit` | Run LLVM regression tests | `llvm-lit -sv llvm/test/Transforms/InstCombine` |
| `llvm-dis` | Disassemble bitcode (.bc) to human-readable IR (.ll) | `llvm-dis input.bc -o output.ll` |
| `llvm-as` | Assemble human-readable IR (.ll) to bitcode (.bc) | `llvm-as input.ll -o output.bc` |
| `llvm-diff` | Structurally compare two IR modules | `llvm-diff a.ll b.ll` |
| `llvm-extract` | Extract specific functions from an IR module | `llvm-extract -func=foo input.ll -o out.ll` |
| `llvm-reduce` | Automatically reduce an IR test case | `llvm-reduce --test=check.sh input.ll` |
| `FileCheck` | Pattern-match tool output against expected patterns | `opt -S input.ll \| FileCheck input.ll` |
| `count` | Count lines (used in lit tests) | `opt -S input.ll \| count 5` |
| `not` | Expect a command to fail (used in lit tests) | `not opt -passes=... input.ll` |
| `alive-tv` | Verify that an IR transformation is semantically correct | `alive-tv src.ll tgt.ll` |

## Common Patterns

### Run a single optimization pass

```bash
opt -passes=instcombine -S input.ll -o output.ll
```

Use `-S` to emit human-readable IR. Without `-S`, opt emits bitcode.

### Run a pass with debug output

```bash
opt -passes=instcombine -S -debug-only=instcombine input.ll 2>debug.log
```

`-debug-only=<name>` requires `LLVM_ENABLE_ASSERTIONS=ON` in the build.
The `<name>` comes from `#define DEBUG_TYPE "..."` in the pass source.
Grep for it: `grep '#define DEBUG_TYPE' llvm/lib/Transforms/InstCombine/*.cpp`

### Run a pass pipeline (multiple passes)

```bash
opt -passes='instcombine,simplifycfg,gvn' -S input.ll
```

Use commas to chain passes. Use parentheses for pass managers:

```bash
opt -passes='function(instcombine,simplifycfg)' -S input.ll
```

### Check if opt crashes on an input

```bash
opt -passes=instcombine -S input.ll
echo $?  # non-zero exit code indicates a crash
```

### Verify a transformation with alive-tv

```bash
# 1. Produce the transformed IR
opt -passes=instcombine -S input.ll -o output.ll

# 2. Verify correctness
alive-tv input.ll output.ll
```

alive-tv reports whether the transformation is correct, incorrect, or inconclusive.
Use `--disable-undef-input` if you get spurious failures from undef inputs.

### Confirm a miscompilation with lli

```bash
# Run original IR
lli input.ll; echo "original: $?"

# Run transformed IR
opt -passes=instcombine -S input.ll -o opt.ll
lli opt.ll; echo "optimized: $?"

# Different exit codes or output = miscompilation confirmed
```

### Run regression tests

```bash
# Run all tests in a directory
llvm-lit -sv llvm/test/Transforms/InstCombine

# Run a single test
llvm-lit -sv llvm/test/Transforms/InstCombine/add.ll

# Stop after first failure (fast debugging)
llvm-lit -sv --max-failures=1 llvm/test/Transforms/

# Run only tests matching a pattern
llvm-lit -sv --filter='add' llvm/test/Transforms/InstCombine
```

### Compare IR before and after a code change

```bash
# Save IR before your edit
opt -passes=instcombine -S input.ll -o before.ll

# Make your code change, rebuild, then:
opt -passes=instcombine -S input.ll -o after.ll

llvm-diff before.ll after.ll
```

### Reduce a test case

```bash
# Create a script that returns 0 when the bug reproduces
cat > /tmp/check.sh << 'EOF'
#!/bin/bash
opt -passes=instcombine -S $1 2>&1 | grep -q "LLVM ERROR"
EOF
chmod +x /tmp/check.sh

# Reduce
llvm-reduce --test=/tmp/check.sh input.ll -o reduced.ll
```

### Compile IR to see generated assembly

```bash
llc -O2 input.ll -o output.s
# Or for object file:
llc -O2 -filetype=obj input.ll -o output.o
```

## References

For detailed usage, flags, and advanced examples, read the reference
files in this skill's `references/` directory:

| Reference | Topics | Grep hint |
|-----------|--------|-----------|
| `references/opt.md` | Pass pipeline syntax, debug flags, common pass names, predefined pipelines | `grep '## ' references/opt.md` |
| `references/llc.md` | Target triples, output types (asm/obj), code generation flags, CPU/feature listing | `grep '## ' references/llc.md` |
| `references/lli.md` | Interpreter vs JIT, exit codes, miscompilation confirmation, limitations | `grep '## ' references/lli.md` |
| `references/llvm-lit.md` | FileCheck directives, RUN/CHECK syntax, check prefixes, auto-generating CHECK lines, test status | `grep '## ' references/llvm-lit.md` |
| `references/alive-tv.md` | Interpreting output (correct/incorrect/inconclusive), known limitations, timeout tuning, attribute sensitivity | `grep '## ' references/alive-tv.md` |

## LLVM Source Documentation

The LLVM source tree contains extensive documentation at `llvm/docs/`
(relative to the LLVM source root). These are `.rst` (reStructuredText)
files that can be read directly. Key files:

| File | Content |
|------|---------|
| `llvm/docs/CodingStandards.rst` | C++ coding standards for LLVM development |
| `llvm/docs/LangRef.rst` | LLVM IR language reference — instruction semantics, types, attributes |
| `llvm/docs/UndefinedBehavior.rst` | LLVM IR Undefined Behavior (UB) Manual |
| `llvm/docs/Passes.rst` | Summary of all analysis and transform passes |
| `llvm/lib/Passes/PassRegistry.def` | The canonical list of all passes, with their command-line names and corresponding implementations |
| `llvm/docs/GetElementPtr.rst` | The often misunderstood GEP instruction: GEP's semantics |
| `llvm/docs/MemorySSA.rst` | MemorySSA design and usage for memory dependence analysis |
| `llvm/docs/LoopTerminology.rst` | Loop terminology and canonical loop forms used in LLVM |
| `llvm/docs/Vectorizers.rst` | Auto-vectorization in LLVM |
| `llvm/docs/VectorizationPlan.rst` | The vectorization plan infrastructure |
| `llvm/docs/LinkTimeOptimization.rst` | LLVM link time optimization: design and implementation |
| `llvm/docs/GlobalISel/index.rst` | GlobalISel instruction selection framework |
| `llvm/docs/TableGen/index.rst` | LLVM's TableGen domain-specific language for code generation and pass registration |
| `llvm/docs/CodeGenerator.rst` | Backend code generation architecture |
| `llvm/docs/OptBisect.rst` | Using -opt-bisect-limit to debug optimization errors |
| `llvm/docs/TestingGuide.rst` | Testing infrastructure: test formats, FileCheck, llvm-lit configuration |
| `llvm/docs/ProgrammersManual.rst` | LLVM C++ API reference — data structures, IR manipulation |
| `llvm/docs/CommandGuide/*.rst` | Man pages for all 59 LLVM command-line tools |

Search the docs for a specific topic:

```bash
# Find which docs mention a concept
grep -rl "InstCombine" llvm/docs/ --include='*.rst'

# Read a specific tool's man page
cat llvm/docs/CommandGuide/opt.rst

# Search for a pass name
grep -n "instcombine" llvm/docs/Passes.rst
```

## Fallback

For any binary not covered above or in the references, run it with `--help`:

```bash
<binary> --help
```
