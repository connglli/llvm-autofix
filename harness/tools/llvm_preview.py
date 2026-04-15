from harness.llvm import FixEnv
from harness.lms.tool import FuncToolSpec, StatelessFuncToolBase


class PreviewTool(StatelessFuncToolBase):
  def __init__(self, env: FixEnv):
    self.env = env

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "llvm_preview_patch",
      "Show the current LLVM diff of all changes you have made so far. "
      "Use this to review your patch before testing, or to check which files you have modified.",
      [],
      keywords=["diff", "patch", "preview", "changes", "git"],
    )

  def _call(self, **kwargs) -> str:
    return self.env.dump_patch()
