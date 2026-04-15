from harness.llvm.debugger import DebuggerBase
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class EvalTool(StatelessFuncToolBase):
  def __init__(self, debugger: DebuggerBase):
    self.debugger = debugger

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "llvm_eval_expr",
      "Evaluate a C++ expression in the current debugger frame and return its value. "
      "Use this to inspect LLVM IR objects, instruction operands, or any in-scope variable. "
      "Make sure you are in the correct stack frame first (use `llvm_debug` to navigate).",
      [
        FuncToolSpec.Param(
          "expr",
          "string",
          True,
          "The expression that you'd like to evaluate and obtain its value",
        ),
      ],
      keywords=["gdb", "debugger", "evaluate", "expression", "variable", "cpp"],
    )

  def _call(self, *, expr: str, **kwargs) -> str:
    """
    Get the value of the expression
    """
    try:
      symbol = self.debugger.eval_symbol(expr)
      if symbol:
        return str(symbol)
      return self.debugger.execute_custom_command(f"print {expr}")
    except Exception as e:
      raise FuncToolCallException(str(e))
