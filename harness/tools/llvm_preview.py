from harness.llvm.intern.lab_env import FixEnv
from harness.lms.tool import FuncToolBase, FuncToolSpec


class PreviewTool(FuncToolBase):
  def __init__(self, env: FixEnv):
    self.env = env

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "preview",
      "Preview the changes made by the current patch.",
      [],
    )

  def _call(self, **kwargs) -> str:
    return self.env.dump_patch()
