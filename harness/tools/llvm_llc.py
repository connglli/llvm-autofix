import shlex
import subprocess
from pathlib import Path

from harness.lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from harness.tools.llvm_mixins import LlvmBuildDirMixin
from harness.utils.cmdline import spawn_process


class CompileIrTool(LlvmBuildDirMixin, FuncToolBase):
  def __init__(self, llvm_build_dir: str):
    LlvmBuildDirMixin.__init__(self, llvm_build_dir)
    self._llc = self._binary_path("llc")

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "compile_ir",
      "Compile an LLVM IR file to target assembly using llc and return the result. "
      "Useful for inspecting code generation decisions or checking how a transformation affects the final assembly. "
      f"Note: uses the llc binary built at {self.llvm_build_dir}, so its behavior reflects any local edits to the LLVM source.",
      [
        FuncToolSpec.Param(
          "input_path",
          "string",
          True,
          "Path to the LLVM IR file to compile. Example: '/tmp/input.ll'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          False,
          "Optional arguments passed to llc. "
          "Example: '-march=x86-64 -mattr=+avx2 -O2' or '-o /tmp/output.s'.",
        ),
      ],
    )

  def _call(self, *, input_path: str, args: str = "", **kwargs) -> str:
    input_file = Path(input_path)
    if not input_file.is_file():
      raise FuncToolCallException(f"Input file not found: {input_path}")

    proc = spawn_process(
      shlex.split(f"{self._llc} {args.strip()} {input_file}"),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      timeout=60,
    )

    if proc.returncode == 0:
      stdout = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
      return stdout if stdout else "Success: output written to file."

    err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
    raise FuncToolCallException(f"llc failed: {err}")
