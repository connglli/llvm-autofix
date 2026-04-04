import subprocess

from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class ResetTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl, base_commit: str):
    self.acl = acl
    self.base_commit = base_commit

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "reset",
      "Restore a file to its original state at the base commit, discarding all local edits. "
      "Use this to undo a broken change before trying a different approach.",
      [
        FuncToolSpec.Param(
          "file",
          "string",
          True,
          "The relative path of the file to edit (starting with llvm/).",
        )
      ],
    )

  def _call(self, *, file: str, **kwargs) -> str:
    self.acl.check_editable(file)
    try:
      subprocess.check_call(
        ["git", "checkout", self.base_commit, file],
        cwd=self.acl.root,
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
    return f"Checked out {file} from commit {self.base_commit}."
