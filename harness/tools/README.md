# Tools

Tools are callable functions exposed to the agent. Each tool is a Python class that describes itself via a `FuncToolSpec`. Tools come in two flavors:

- **Stateless** — no mutable state between calls. Inherit from `StatelessFuncToolBase`.
- **Stateful** — holds mutable state (e.g. a todo list). Inherit from `StatefulFuncToolBase` and implement `fresh()` to return a new, clean instance.

When a skill or sub-agent sub-loop runs, every tool is `fresh()`-ed so the sub-loop gets clean state. Stateless tools return `self`; stateful tools return a new instance. `SkillTool` instances are rebound to the sub-agent via `for_agent()` instead of `fresh()`, since they hold an agent reference.

## Writing a Stateless Tool

```python
from harness.lms.tool import StatelessFuncToolBase, FuncToolCallException, FuncToolSpec


class MyTool(StatelessFuncToolBase):
  def __init__(self, ...):
    ...

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "tool_name",
      "Description of what the tool does and when to use it.",
      [
        FuncToolSpec.Param("param", "string", True, "Description of the parameter."),
        FuncToolSpec.Param("optional", "string", False, "Optional parameter."),
      ],
    )

  def _call(self, *, param: str, optional: str = "", **kwargs) -> str:
    ...
    return "result"
```

## Writing a Stateful Tool

```python
from harness.lms.tool import StatefulFuncToolBase, FuncToolCallException, FuncToolSpec


class MyStatefulTool(StatefulFuncToolBase):
  def __init__(self):
    self.items = []

  def fresh(self) -> "MyStatefulTool":
    return MyStatefulTool()  # clean instance with empty state

  def spec(self) -> FuncToolSpec:
    ...

  def _call(self, **kwargs) -> str:
    ...
```

- `_call` must return a string. Raise `FuncToolCallException` on errors — the registry catches it and returns the message to the agent as an error string.
- Always include `**kwargs` in `_call` to absorb unexpected parameters from the LLM.
- Keep `spec()` pure (no side effects). It is called repeatedly to render the tool schema.

## Tool Descriptions

The description is the primary interface between the tool and the model. Write it to answer:
1. **What** the tool does and what it returns.
2. **When** to reach for it (concrete use cases).
3. **What** notable behavior or constraints the caller should know.

Avoid mentioning implementation details (binary names, internal paths) unless they directly affect how the caller should use the tool.

## Naming Conventions

### File names
- Generic tools (file I/O, search, shell): plain name, e.g. `edit.py`, `bash.py`, `subagent.py`.
- LLVM-specific tools: `llvm_` prefix, e.g. `llvm_debug.py`, `llvm_opt.py`.

### Tool names (exposed to the agent)
- Use `snake_case`.
- LLVM IR tools append `_ir` to indicate the input/output domain: `llvm_optimize_ir`, `llvm_verify_ir`, `llvm_compile_ir`, `llvm_execute_ir`, `llvm_interpret_ir`, `llvm_miscompile_check`, etc.
- LLVM-specific tools use an `llvm_` prefix in the tool name: `llvm_test`, `llvm_debug`, `llvm_code`, etc.

### Class names
- `PascalCase` with a `Tool` suffix, e.g. `OptimizeIrTool`, `DebugTool`.

## Access Control

Tools that read or write files in the LLVM source tree take an `AccessControl` instance (from `harness.llvm.access`). Use it to validate paths before operating:

```python
from harness.llvm.access import AccessControl


class MyTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl):
    self.acl = acl

  def _call(self, *, file: str, **kwargs) -> str:
    full_path = self.acl.check_readable_file(file)   # read-only
    # or
    full_path = self.acl.check_editable_file(file)   # read-write
    ...
```

`AccessControl` enforces configurable editable/readable/ignored path patterns (fnmatch wildcards supported) and prevents path traversal outside the workspace root.

## Tools Using LLVM Builds

Tools that invoke binaries from an LLVM build directory should inherit `LlvmBuildDirMixin`:

```python
from harness.tools.llvm_mixins import LlvmBuildDirMixin


class MyLlvmTool(LlvmBuildDirMixin, StatelessFuncToolBase):
  def __init__(self, llvm_build_dir: str):
    LlvmBuildDirMixin.__init__(self, llvm_build_dir)
    self._binary = self._binary_path("my-binary")  # validated lazily at call time
```

`LlvmBuildDirMixin` resolves binary paths eagerly but validates them lazily via `_check()` before each call. This means the tool is always registered — if LLVM hasn't been built yet, the agent gets an actionable error telling it to run `llvm_build`.

## Harness-Managed vs Client-Managed Tools

**Harness-managed** tools are created by `Harness.make_tools()`. Their availability is gated by harness state (build dir, debugger, fixenv). Clients select from them by name and assign budgets.

| Dependency | Tools |
|---|---|
| Always | `read`, `list`, `find`, `ripgrep`, `edit`, `write`, `bash`, `insight`, `llvm_optimize_ir`, `llvm_compile_ir`, `llvm_execute_ir`, `llvm_interpret_ir`, `llvm_miscompile_check` |
| alive-tv | `llvm_verify_ir` |
| fixenv | `llvm_build`, `llvm_test`, `llvm_reset`, `llvm_preview_patch` |
| debugger | `llvm_code`, `llvm_docs`, `llvm_debug`, `llvm_eval_expr`, `llvm_langref` |

**Client-managed** tools are defined and registered by the client (e.g. `autofix/mini.py`), not by the harness. They typically encode workflow-specific logic that doesn't belong in the shared harness.

| Tool | File | Description |
|---|---|---|
| `subagent` | `subagent.py` | Spawns a stateless sub-agent. Requires an agent reference at construction time. |
| `todo` | `todo.py` | Stateful todo list for agent self-tracking. |
| `askq` | `askq.py` | Ask the user a question. |
| *(app-defined)* | *(in client code)* | e.g. `submit_analysis`, `submit_patchreport` in autofix. |

Client-managed tools are registered directly on the agent after creation:

```python
agent = agent_config.create_agent(tools=harness_tools, skills=skills)
agent.register_tool(SubAgentTool(agent), budget=10)
```
