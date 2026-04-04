# lli — LLVM Bitcode Interpreter / JIT Compiler

`lli` directly executes LLVM IR programs using a JIT compiler or interpreter.
It runs on the host architecture only — it is **not** an emulator.

## Basic Usage

```bash
# JIT-compile and run (default)
lli input.ll

# Force interpreter mode (slower, but more predictable)
lli -force-interpreter=true input.ll

# Pass arguments to the program
lli input.ll arg1 arg2

# Read from stdin
opt -O2 -S input.ll | llvm-as | lli
```

## Useful Flags

| Flag | Description |
|------|-------------|
| `-force-interpreter=true` | Use interpreter instead of JIT (default: false) |
| `-fake-argv0=<name>` | Override argv[0] passed to the program |
| `-stats` | Print JIT code-generation statistics |
| `-time-passes` | Time each code-generation pass |
| `-mtriple=<triple>` | Override target triple |
| `-mcpu=<cpu>` | Target a specific CPU |
| `-mattr=<attrs>` | Enable/disable target features |

## Exit Code

`lli` returns the exit code of the executed program, or 1 if it fails
to load the input. This is important for miscompilation diagnosis:

```bash
# Compare exit codes before and after transformation
lli original.ll; echo "original: $?"
lli transformed.ll; echo "transformed: $?"
```

## Common Use Cases

### Confirming a Miscompilation

```bash
# 1. Run the original IR
lli input.ll
echo "Exit code: $?"

# 2. Transform and run
opt -passes=instcombine -S input.ll -o optimized.ll
lli optimized.ll
echo "Exit code: $?"

# Different exit codes or output = miscompilation confirmed
```

### Checking Runtime Behavior

```bash
# Run IR that prints output
lli program.ll
# stdout/stderr come from the executed program
```

## Limitations

- **Host architecture only.** Cannot execute IR targeting a different
  architecture.
- **JIT mode** may behave differently from static compilation (`llc`) in
  edge cases.
- **Interpreter mode** is slow but faithfully executes IR semantics. Use
  `-force-interpreter=true` when JIT results are suspicious.
- Programs that use external libraries (beyond libc) may fail to resolve
  symbols.

## See Also

- `llvm/docs/CommandGuide/lli.rst` in the LLVM source tree for full
  option reference.
