# llc — LLVM Static Compiler

`llc` compiles LLVM IR to native assembly or object code for a target
architecture. The target is inferred from the input's target triple or
can be overridden with flags.

## Basic Usage

```bash
# Compile IR to assembly (default)
llc input.ll -o output.s

# Compile IR to object file
llc -filetype=obj input.ll -o output.o

# Compile with optimization
llc -O2 input.ll -o output.s

# Read from stdin
opt -O2 -S input.ll | llvm-as | llc -o output.s
```

## Useful Flags

| Flag | Description |
|------|-------------|
| `-o <file>` | Output file (default: stdout or derived from input name) |
| `-O=<level>` | Optimization level: 0, 1, 2, 3 |
| `-filetype=<type>` | Output type: `asm` (default), `obj`, `null` |
| `-mtriple=<triple>` | Override target triple (e.g., `x86_64-unknown-linux-gnu`) |
| `-march=<arch>` | Target architecture (e.g., `x86`, `aarch64`, `riscv64`) |
| `-mcpu=<cpu>` | Target specific CPU model |
| `-mattr=<attrs>` | Enable/disable target features (e.g., `+avx2,-sse`) |
| `--frame-pointer=<mode>` | Frame pointer: `all`, `non-leaf`, `none` |
| `--print-after-isel` | Print machine code after instruction selection |
| `--regalloc=<alloc>` | Register allocator: `fast`, `greedy`, `basic`, `pbqp` |
| `--stats` | Print code-generation statistics |
| `--time-passes` | Time each code-generation pass |
| `--x86-asm-syntax=<style>` | X86 assembly syntax: `att` (default) or `intel` |

## Common Use Cases

### Inspect Code Generation

```bash
# See what assembly a pass produces
opt -passes=instcombine -S input.ll | llvm-as | llc -O2 -o - | less
```

### Check How a Transformation Affects Assembly

```bash
# Before
llc -O2 original.ll -o before.s

# After your LLVM source change + rebuild
llc -O2 original.ll -o after.s

diff before.s after.s
```

### List Available Targets and CPUs

```bash
# List architectures
llc --version

# List CPUs for an architecture
llvm-as < /dev/null | llc -march=x86 -mcpu=help

# List features for an architecture
llvm-as < /dev/null | llc -march=x86 -mattr=help
```

### Generate Object Files

```bash
llc -filetype=obj input.ll -o output.o
# Then link:
gcc output.o -o executable
```

## Target Triples

The target triple format is `<arch>-<vendor>-<os>-<env>`:

| Triple | Description |
|--------|-------------|
| `x86_64-unknown-linux-gnu` | 64-bit x86 Linux |
| `aarch64-unknown-linux-gnu` | 64-bit ARM Linux |
| `riscv64-unknown-linux-gnu` | 64-bit RISC-V Linux |
| `x86_64-apple-darwin` | 64-bit x86 macOS |

Override with `-mtriple` when the input IR has the wrong (or no) triple.

## Exit Code

`llc` exits with 0 on success, non-zero on failure. A non-zero exit
usually means the input IR is invalid or the target doesn't support
a required feature.

## See Also

- `llvm/docs/CommandGuide/llc.rst` in the LLVM source tree for full
  option reference.
- `llvm/docs/CodeGenerator.rst` for code generation architecture details.
