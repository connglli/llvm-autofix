from harness.llvm import FixEnv
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class BuildTool(StatelessFuncToolBase):
  def __init__(self, fixenv: FixEnv):
    self.fixenv = fixenv

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "llvm_build",
      "Build LLVM from the current source tree. "
      "Call this after editing source files and before running any tools "
      "that depend on the build (e.g., llvm_optimize_ir, llvm_compile_ir, llvm_interpret_ir). "
      "Returns whether the build succeeded and the build log.",
      [],
    )

  def _call(self, **kwargs) -> str:
    try:
      success, log = self.fixenv.build()
    except Exception as e:
      raise FuncToolCallException(f"Build failed: {e}")
    if success:
      return f"Build succeeded.\n{log}"
    raise FuncToolCallException(f"Build failed.\n{log}")
