from harness.llvm.intern.lab_env import FixEnv
from harness.lms.tool import FuncToolSpec, StatelessFuncToolBase


class PreviewTool(StatelessFuncToolBase):
  def __init__(self, env: FixEnv):
    self.env = env

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "preview",
      "Show the current diff of all changes you have made so far. "
      "Use this to review your patch before testing, or to check which files you have modified.",
      [],
    )

  def _call(self, **kwargs) -> str:
    return self.env.dump_patch()
