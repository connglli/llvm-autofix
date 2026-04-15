import shlex
import subprocess
from pathlib import Path

from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase
from harness.tools.llvm_mixins import LlvmBuildDirMixin
from harness.utils.cmdline import spawn_process


class ExecuteIrTool(LlvmBuildDirMixin, StatelessFuncToolBase):
  def __init__(self, llvm_build_dir: str):
    LlvmBuildDirMixin.__init__(self, llvm_build_dir)
    self._lli = self._binary_path("lli")

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "llvm_execute_ir",
      "Execute an LLVM IR file using the LLVM executor (i.e., lli) and return its output and exit code. "
      "Useful for checking the runtime behavior of an IR program, or confirming a miscompilation "
      "by comparing execution results before and after a transformation. "
      f"Note: uses the lli binary built at {self.llvm_build_dir}, so its behavior reflects any local edits to the LLVM source.",
      [
        FuncToolSpec.Param(
          "input_path",
          "string",
          True,
          "Path to the LLVM IR file to execute. Example: '/tmp/input.ll'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          False,
          "Optional arguments passed to lli before the input file. "
          "Example: '-jit-kind=mcjit'.",
        ),
      ],
    )

  def _call(self, *, input_path: str, args: str = "", **kwargs) -> str:
    input_file = Path(input_path)
    if not input_file.is_file():
      raise FuncToolCallException(f"Input file not found: {input_path}")

    proc = spawn_process(
      shlex.split(f"{self._lli} {args.strip()} {input_file}"),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      timeout=60,
    )

    stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")

    parts = [f"Exit code: {proc.returncode}"]
    if stdout.strip():
      parts.append(f"stdout:\n{stdout.rstrip()}")
    if stderr.strip():
      parts.append(f"stderr:\n{stderr.rstrip()}")
    return "\n".join(parts)
