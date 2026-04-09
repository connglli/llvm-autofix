import re

from harness.llvm import LlvmCode
from harness.llvm.debugger import DebuggerBase
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class DocsTool(StatelessFuncToolBase):
  def __init__(self, llvm: LlvmCode, debugger: DebuggerBase):
    self.llvm = llvm
    self.debugger = debugger
    self.pattern = re.compile('Line (\\d+) of "([^"]+)" starts at')

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "docs",
      "Retrieve the header comment / documentation of an LLVM C++ function by name. "
      "Use this to understand a function's purpose and contract before reading its implementation.",
      [FuncToolSpec.Param("func", "string", True, "Name of the function")],
    )

  def _call(self, *, func: str, **kwargs) -> str:
    """
    Get the document from LLVM, perhaps we should build a database
    We use the header comments of the function for now.
    """
    try:
      res = self.debugger.execute_custom_command(f"info line {func}")
      match = re.search(self.pattern, res)
      if match:
        return self.llvm.render_func_code(
          func,
          int(match.group(1)),
          match.group(2),
        ).header
      return "Unavailable"
    except Exception as e:
      raise FuncToolCallException(str(e))
