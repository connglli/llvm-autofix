from harness.llvm.intern.llvm_code import LlvmCode
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class LangRefTool(StatelessFuncToolBase):
  def __init__(self, llvm: LlvmCode):
    self.llvm = llvm

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "langref",
      "Look up the semantics of an LLVM IR instruction or intrinsic from the Language Reference Manual. "
      "Use this when you need to understand the exact behavior of an instruction (e.g., `select`, `phi`, `llvm.uadd.with.overflow`) "
      "to reason about correctness or diagnose a miscompilation.",
      [
        FuncToolSpec.Param(
          "inst",
          "string",
          True,
          "The instruction/intrinsic that you'd like to get the description for.\n"
          "For instructions, please provide the instruction name (e.g., `add`, `mul`, etc.).\n"
          "For intrinsics, please provide the intrinsic name (e.g., `llvm.sadd.with.overflow`, `llvm.memcpy`, etc.).\n"
          "Do not include type mangling suffix or operands in the name.",
        ),
      ],
    )

  def _call(self, *, inst: str, **kwargs) -> str:
    res = self.llvm.parse_langref_desc([inst])
    if inst in res:
      return res[inst]
    raise FuncToolCallException(
      f"'{inst}' is not found in the LLVM Language Reference Manual."
    )
