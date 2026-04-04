# Harness

`harness.llvm.Harness` is the single entry point for working with LLVM in this project. It manages the LLVM workspace, provides tools and skills to agents, and handles bug reproduction.

```python
from harness.llvm import Harness
```

## Quick Start

```python
# Fix a bench issue with an internal agent
with Harness.from_issue("99899", cmake_args=[...]) as h:
    rep = h.reproduce()
    agent = MyAgent(model, ...)
    for tool in h.make_tools():
        agent.register_tool(tool, budget=250)
    agent.run(prompt, **vars(rep))

# Fix a bench issue with an external code agent (Claude Code, Gemini CLI)
with Harness.from_issue("99899") as h:
    rep = h.reproduce()
    prompt = TEMPLATE.format(
        issue_type=rep.bug_type,
        llvm_dir=str(h.llvm_dir),
        build_dir=str(h.build_dir),
        ...
    )
    run_xcli(prompt)

# Work on an ad-hoc bug from an IR file
with Harness.from_reproducer("crash.ll", "opt -passes=instcombine -S", "crash") as h:
    rep = h.reproduce()
    ...

# General LLVM workspace (superopt, dev)
with Harness.workspace() as h:
    h.build()
    opt = h.make_tool("optimize_ir")
    opt.call(input_path="test.ll", args="-O2 -S")
```

## Factory Methods

Create a Harness with the factory method matching your scenario. Do not call `__init__` directly.

### `Harness.workspace(**acl)`

Bare LLVM workspace. No issue, no reproduction. Use for superoptimization, general development, or any task that just needs LLVM built.

### `Harness.from_issue(issue_id, **options)`

Load a bench issue from `bench/`. On `__enter__`, sets the build directory to `{LAB_LLVM_BUILD_DIR}/{issue_id}` and resets the LLVM repo to the issue's base commit.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `issue_id` | `str` | required | Issue ID from bench/ |
| `cmake_args` | `list[str]` | `[]` | Extra CMake flags for the build |
| `max_build_jobs` | `int` | CPU count | Parallel build jobs |
| `max_test_jobs` | `int` | same as build | Parallel test jobs |
| `aggressive_testing` | `bool` | `False` | Run entire regression suite |
| `model_knowledge_cutoff` | `str` | `"2023-12-31Z"` | Knowledge cutoff for the agent |

### `Harness.from_reproducer(file, command, bug_type, **acl)`

Ad-hoc bug from a user-provided IR file. No bench issue JSON required.

| Parameter | Type | Description |
|---|---|---|
| `file` | `str \| Path` | Path to the IR reproducer file |
| `command` | `str` | Command template (e.g. `"opt -passes=instcombine -S"`) |
| `bug_type` | `str` | `"crash"`, `"miscompilation"`, or `"hang"` |

### Access Control (all factory methods)

All factory methods accept optional access control parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `acl_preset` | `str` | `"llvm"` | ACL preset name (`"llvm"` or `"llvm+clang"`) |
| `extra_editable` | `list[str]` | `[]` | Additional editable path patterns |
| `extra_readable` | `list[str]` | `[]` | Additional readable path patterns |
| `extra_ignored` | `list[str]` | `[]` | Additional ignored path patterns |

Presets define sensible defaults (e.g., `"llvm"` makes `llvm/lib` and `llvm/include` editable, the whole `llvm/` tree readable). `/tmp/` is always readable and writable. The build directory and skills directory are added automatically. Patterns use `fnmatch` syntax (`*`, `?`, `[seq]`). A bare directory name (no wildcards) matches everything underneath.

## Context Manager

Always use Harness as a context manager:

```python
with Harness.from_issue("99899") as h:
    ...
```

`__enter__` handles:
- For `from_issue`: sets the per-issue build directory and resets the LLVM repo to the base commit (with automatic retry on failure).
- For `from_reproducer` and `workspace`: no-op.

## Properties

| Property | Type | Description |
|---|---|---|
| `h.llvm_dir` | `Path` | LLVM source root (from `LAB_LLVM_DIR`) |
| `h.build_dir` | `Path` | Current build directory (from `LAB_LLVM_BUILD_DIR`) |
| `h.alive_tv` | `str \| None` | Path to alive-tv binary (from `LAB_LLVM_ALIVE_TV`) |
| `h.fixenv` | `FixEnv \| None` | Bench issue environment (only for `from_issue`) |
| `h.llvmcode` | `LlvmCode` | Lazily-created LLVM source analysis toolkit |
| `h.debugger` | `DebuggerBase \| None` | Attached debugger (after `attach_debugger`) |
| `h.acl` | `AccessControl` | File access control policy |

## Operations

### `h.reproduce() -> Reproducer`

Build LLVM and reproduce the configured bug. Returns a `Reproducer` dataclass:

```python
@dataclass
class Reproducer:
    issue_id: str          # Issue ID or "adhoc"
    bug_type: str          # "crash" | "miscompilation" | "hang"
    file_path: Path        # Path to the reproducer .ll file
    command: list[str]     # Resolved opt command tokens
    raw_command: str       # Original command template
    source: str            # IR source text
    symptom: str           # Rendered symptom log
```

- For `from_issue`: calls `fixenv.check_fast()` (builds + runs reproducer tests), parses the result.
- For `from_reproducer`: runs the command on the file and verifies the bug manifests.
- For `workspace`: raises `RuntimeError`.

### `h.build() -> tuple[bool, str]`

Build LLVM. Returns `(success, log)`. Delegates to `fixenv.build()` when available.

### `h.run_opt(file, args, *, check=True, **kwargs) -> tuple[str, str]`

Run `opt` on a file with the given arguments. Returns `(command, output)`.

### `h.apply_patch(patch: str) -> tuple[bool, str]`

Apply a unified diff patch to the LLVM source tree. Returns `(success, log)`.

### `h.git(*args) -> str`

Run a git command in the LLVM source directory.

## Debugger

```python
debugger = h.attach_debugger(reproducer.command)
backtrace, breakpoint = debugger.run(h.llvm_dir, breakpoints, is_miscompilation)
```

After attaching, `h.make_tools()` includes debugger-dependent tools (`code`, `docs`, `debug`, `eval`).

## Source Analysis (`h.llvmcode`)

The `llvmcode` property provides LLVM C++ source analysis:

```python
# Resolve opt pass names
pass_name, analysis = h.llvmcode.resolve_pass_name(command)
opts = h.llvmcode.resolve_pass_opts(pass_name)

# Find DEBUG_TYPE values in source files
debug_types = h.llvmcode.resolve_debug_types({Path("llvm/lib/Transforms/Scalar/GVN.cpp")})

# Render a function's source code
snippet = h.llvmcode.render_func_code("GVN::runImpl", 42, "llvm/lib/Transforms/Scalar/GVN.cpp")
print(snippet.render())

# Extract a code snippet by line range
code = h.llvmcode.extract_snippet("llvm/lib/IR/Value.cpp", 100, 120, context=5)

# Parse IR keywords
keywords = h.llvmcode.parse_ir_keywords(ir_text)

# Look up LangRef documentation
docs = h.llvmcode.parse_langref_desc(keywords)

# Infer LLVM components from changed files
components = h.llvmcode.infer_related_components(["llvm/lib/Transforms/Scalar/GVN.cpp"])
```

## Tools

`h.make_tools()` returns all tool instances available given the current state:

| Dependency | Tools provided |
|---|---|
| Always | `read`, `list`, `find`, `ripgrep`, `edit`, `write`, `bash` |
| build_dir | `optimize_ir`, `compile_ir`, `interpret_ir`, `verify_ir` |
| fixenv | `test`, `reset`, `preview`, `langref` |
| debugger | `code`, `docs`, `debug`, `eval` |

```python
# Get all tools
tools = h.make_tools()

# Get a single tool by name
tester = h.make_tool("test")

# Register tools into an agent with budgets
for tool in h.make_tools():
    agent.register_tool(tool, budget=250)
```

## Skills

```python
# List available skills
skills = h.get_skills()

# Get a skill by name
skill_path = h.get_skill("llvm-patchreview")

# Install a skill into a target directory (e.g., for Claude Code)
h.install_skill("llvm-patchreview", Path(".claude"), exists_ok=True)
```

## Environment Variables

The Harness requires these environment variables (typically set by `source buildscripts/upenv.sh`):

| Variable | Description |
|---|---|
| `LAB_LLVM_DIR` | Path to the LLVM source tree |
| `LAB_LLVM_BUILD_DIR` | Base path for LLVM build directories |
| `LAB_LLVM_ALIVE_TV` | Path to the alive-tv binary |
| `LAB_DATASET_DIR` | Path to the bench issue dataset |
