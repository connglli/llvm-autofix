import subprocess

from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class ResetTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl, base_commit: str, git_root: str):
    self.acl = acl
    self.base_commit = base_commit
    self.git_root = git_root

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
      subprocess.check_call(
        ["git", "-C", self.git_root, "checkout", self.base_commit, str(resolved)],
      )
    except subprocess.CalledProcessError as e:
      raise FuncToolCallException(
        f"Failed to checkout {file}: "
        + str(e)
        + "\n"
        + (e.output.decode() if e.output else "")
        + "\n"
        + (e.stderr.decode() if e.stderr else ""),
      )
    return f"Successfully restored {resolved}"
