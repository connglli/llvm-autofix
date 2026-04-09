from harness.llvm.access import AccessControl
from harness.llvm.intern.lab_env import FixEnv
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class ResetTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl, fixenv: FixEnv):
    self.acl = acl
    self.fixenv = fixenv

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "reset",
      "Restore an LLVM file to its original state, discarding all local edits. "
      "Use this to undo a broken change before trying a different approach. "
      "Note that this will lead to stale LLVM builds, so `llvm_build` should be "
      "called before calling any other tools that depend on the build. E.g., "
      "llvm_optimize_ir, llvm_compile_ir, etc.",
      [
        FuncToolSpec.Param(
          "file",
          "string",
          True,
          "The absolute path of the file to reset.",
        )
      ],
    )

  def _call(self, *, file: str, **kwargs) -> str:
    resolved = self.acl.check_editable(file)
    try:
      self.fixenv.reset(files=[str(resolved)])
    except Exception as e:
      raise FuncToolCallException(
        f"Failed to reset {file}: {e}",
      )
    return f"Successfully restored {resolved}"
