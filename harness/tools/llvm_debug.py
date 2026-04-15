from harness.llvm.debugger import DebuggerBase
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class DebugTool(StatelessFuncToolBase):
  def __init__(self, debugger: DebuggerBase):
    self.debugger = debugger

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "llvm_debug",
      "Execute a GDB command in the attached debugger session and return the result. "
      "The debugger is paused at the crash site or transformation breakpoint of LLVM. "
      "Use this to inspect the call stack, print variables, navigate frames, or set watchpoints. "
      "Commands that start new sessions (run/start/quit) or invoke shell (shell/make/pipe) are forbidden.",
      [
        FuncToolSpec.Param("cmd", "string", True, "The GDB command"),
      ],
      keywords=["gdb", "debugger", "breakpoint", "backtrace", "step"],
    )

  def _call(self, *, cmd: str, **kwargs) -> str:
    """
    Execute the debugger command
    """
    try:
      return self.debugger.execute_custom_command(cmd)
    except Exception as e:
      raise FuncToolCallException(str(e))
