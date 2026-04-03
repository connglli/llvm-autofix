import re
from pathlib import Path

from harness.llvm.debugger import DebuggerBase
from harness.llvm.intern.llvm_code import LlvmCode
from harness.lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


# TODO: There is a chance that a function is excessively long
class CodeTool(FuncToolBase):
  def __init__(self, llvm: LlvmCode, debugger: DebuggerBase):
    self.llvm = llvm
    self.debugger = debugger
    self.pattern = re.compile('Line (\\d+) of "([^"]+)" starts at')

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "code",
      "Retrieve the full source code of an LLVM C++ function by name, using the debugger to resolve its location. "
      "Use this to read a pass function, utility, or IR builder method without manually searching for it.",
      [FuncToolSpec.Param("func", "string", True, "Name of the function")],
    )

  def _call(self, *, func: str, **kwargs) -> str:
    """
    Get the code of the func from LLVM, perhaps we should build a database
    """
    try:
      res = self.debugger.execute_custom_command(f"info line {func}")
      match = re.search(self.pattern, res)
      if match:
        return self.llvm.render_func_code(
          func,
          int(match.group(1)),
          Path(match.group(2)).relative_to(self.llvm.llvm_dir),
        ).render()
      return "Unavailable"
    except Exception as e:
      raise FuncToolCallException(str(e))
