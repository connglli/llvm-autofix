# llubi — LLVM UB-aware Interpreter

`llubi` directly executes programs in LLVM bitcode format and tracks values
in LLVM IR semantics. Unlike `lli`, `llubi` is designed to be aware of
undefined behaviors during execution. It detects immediate undefined behaviors
such as integer division by zero, and respects poison-generating flags like
`nsw` and `nuw`. This makes it highly suitable for constructing
interestingness tests for miscompilation bugs.

**Available since LLVM 23.0.0.**

## Basic Usage

```bash
# Execute an IR file
llubi input.ll

# Pass arguments to the program
llubi input.ll arg1 arg2

# Specify a different entry function
llubi -entry-function=test input.ll

# Read from stdin
opt -O2 -S input.ll | llvm-as | llubi
```

## Useful Flags

| Flag | Description |
|------|-------------|
| `-entry-function=<name>` | Entry point function (default: `main`) |
| `-fake-argv0=<name>` | Override argv[0] passed to the program |
| `-verbose` | Print results for each instruction executed |
| `-max-mem=<N>` | Memory limit in bytes (default: 0 = unlimited) |
| `-max-stack-depth=<N>` | Maximum stack depth (default: 256, 0 = unlimited) |
| `-max-steps=<N>` | Maximum instructions executed (default: 0 = unlimited) |
| `-vscale=<N>` | Value of `llvm.vscale` (default: 4) |
| `-seed=<N>` | Random number generator seed (default: 0) |
| `-undef-behavior=<mode>` | How to handle undefined values (see below) |

### Undefined Behavior Modes (`-undef-behavior`)

| Mode | Description |
|------|-------------|
| `nondet` | Each load from uninitialized memory yields a fresh random value (default) |
| `zero` | Uninitialized values are treated as zero |

## Exit Code

- If `llubi` fails to load the program or an immediate undefined behavior is
  triggered, it exits with code **1**.
- If the entry function's return type is not an integer type, it returns **0**.
- Otherwise, it returns the exit code of the program.

This is critical for miscompilation diagnosis — a UB-triggered exit code 1
distinguishes "the optimization exposed UB" from "the optimization changed
observable behavior."

## Common Use Cases

### Confirming a Miscompilation

```bash
# 1. Run the original IR
llubi input.ll
echo "original: $?"

# 2. Transform and run
opt -passes=instcombine -S input.ll -o optimized.ll
llubi optimized.ll
echo "optimized: $?"

# Different exit codes or output = miscompilation confirmed
```

### Detecting Undefined Behavior

```bash
# llubi exits with 1 if it encounters immediate UB
llubi -verbose suspect.ll
# Check stderr for UB diagnostics
```

### Limiting Resource Usage

```bash
# Prevent infinite loops or excessive memory use
llubi -max-steps=100000 -max-mem=67108864 input.ll
```

## llubi vs lli

| | `llubi` | `lli` |
|---|---|---|
| UB detection | Yes (division by zero, poison flags) | No |
| Execution model | Interpreter only | JIT or interpreter |
| Speed | Slower (tracks IR semantics) | Faster (JIT compiled) |
| Poison/undef handling | Faithful to IR semantics | Native execution (UB is silent) |
| Use case | Miscompilation diagnosis, IR correctness | Performance testing, quick execution |
| Availability | LLVM >= 23.0.0 | All LLVM versions |

When diagnosing miscompilations, prefer `llubi` over `lli`. If `llubi`
crashes or is unavailable, fall back to `lli`.

## See Also

- `llvm/docs/CommandGuide/llubi.rst` in the LLVM source tree for full
  option reference.
