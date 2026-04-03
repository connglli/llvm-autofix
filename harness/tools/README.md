# Tools

Tools are callable functions exposed to the agent. Each tool is a Python class that inherits from `FuncToolBase` and describes itself via a `FuncToolSpec`.

## Writing a Tool

```python
from harness.lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class MyTool(FuncToolBase):
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
- Generic tools (file I/O, search, shell): plain name, e.g. `edit.py`, `bash.py`.
- LLVM-specific tools: `llvm_` prefix, e.g. `llvm_debug.py`, `llvm_opt.py`.

### Tool names (exposed to the agent)
- Use `snake_case`.
- LLVM IR tools append `_ir` to indicate the input/output domain: `optimize_ir`, `verify_ir`, `compile_ir`, `interpret_ir`.
- Generic-sounding LLVM tools (debugger, test runner, etc.) do **not** get an `llvm_` prefix in the tool name — the description provides that context.

### Class names
- `PascalCase` with a `Tool` suffix, e.g. `OptimizeIrTool`, `DebugTool`.

## Access Control

Tools that read or write files in the LLVM source tree take an `AccessControl` instance (from `harness.llvm.access`). Use it to validate paths before operating:

```python
from harness.llvm.access import AccessControl


class MyTool(FuncToolBase):
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


class MyLlvmTool(LlvmBuildDirMixin, FuncToolBase):
  def __init__(self, llvm_build_dir: str):
    LlvmBuildDirMixin.__init__(self, llvm_build_dir)
    self._binary = self._binary_path("my-binary")  # validated eagerly
```

`LlvmBuildDirMixin` requires a completed LLVM build and validates the build directory at construction time.

## Registering Tools

Tools are registered with the harness at runtime. See `Harness.make_tools()` for the current registration logic.
