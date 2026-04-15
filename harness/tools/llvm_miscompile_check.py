import shlex
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from harness.llvm.intern.llvm import is_opt_crash
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase
from harness.tools.llvm_mixins import LlvmBuildDirMixin
from harness.utils.cmdline import spawn_process


class MiscompileCheckTool(LlvmBuildDirMixin, StatelessFuncToolBase):
  def __init__(self, llvm_build_dir: str):
    LlvmBuildDirMixin.__init__(self, llvm_build_dir)
    self._opt = self._binary_path("opt")
    self._llubi = self._binary_path("llubi")
    self._lli = self._binary_path("lli")

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "llvm_miscompile_check",
      "Check whether an LLVM optimization pass miscompiles a single IR program. "
      "Given an IR file (which must define a @main function) and opt arguments, "
      "this tool: (1) runs opt to produce the optimized IR, "
      "(2) executes both original and optimized IR using llubi (or lli as fallback), "
      "and (3) compares the results. "
      "Use this to confirm or discover miscompilations on individual IR test cases. "
      "If llubi crashes, set `use_lli` to true to fall back to lli.",
      [
        FuncToolSpec.Param(
          "input_path",
          "string",
          True,
          "Path to the LLVM IR file to check. "
          "The file must define a @main function as the entry point. "
          "Example: '/tmp/input.ll'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          True,
          "Arguments for opt to specify the optimization pass. "
          "Example: '-S -passes=instcombine'.",
        ),
        FuncToolSpec.Param(
          "use_lli",
          "boolean",
          False,
          "If true, use lli instead of llubi for execution. "
          "Use this if llubi crashes or has issues. Defaults to false.",
        ),
      ],
    )

  def _optimize(self, ir_path: Path, args: str, output_path: Path) -> None:
    """Run opt on the IR file. Raises on failure or crash."""
    proc = spawn_process(
      shlex.split(f"{self._opt} {args} {ir_path} -o {output_path}"),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      timeout=60,
    )

    if proc.returncode == 0:
      return

    err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
    if is_opt_crash(err):
      raise FuncToolCallException(f"opt crashed:\n{err}")
    raise FuncToolCallException(f"opt failed:\n{err}")

  def _execute(self, ir_path: Path, use_lli: bool, timeout_s: int = 10) -> dict:
    """Execute an IR file and return the result."""
    executor = self._lli if use_lli else self._llubi
    executor_name = "lli" if use_lli else "llubi"

    try:
      res = subprocess.run(
        [str(executor), str(ir_path)],
        capture_output=True,
        timeout=timeout_s,
      )
      return {
        "timed_out": False,
        "return_code": res.returncode,
        "stdout": res.stdout.decode("utf-8", errors="replace").strip(),
        "stderr": res.stderr.decode("utf-8", errors="replace").strip(),
        "executor": executor_name,
      }
    except subprocess.TimeoutExpired as e:
      return {
        "timed_out": True,
        "return_code": None,
        "stdout": (
          e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        ).strip(),
        "stderr": (
          e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        ).strip(),
        "executor": executor_name,
      }

  def _call(
    self,
    *,
    input_path: str,
    args: str,
    use_lli: bool = False,
    **kwargs,
  ) -> str:
    input_file = Path(input_path)
    if not input_file.is_file():
      raise FuncToolCallException(f"Input file not found: {input_path}")

    with TemporaryDirectory() as tmpdir:
      output_file = Path(tmpdir) / "optimized.ll"

      self._optimize(input_file, args, output_file)

      orig_result = self._execute(input_file, use_lli)
      opt_result = self._execute(output_file, use_lli)

      parts = []

      def _fmt(label: str, result: dict) -> None:
        parts.append(f"--- {label} ({result['executor']}) ---")
        if result["timed_out"]:
          parts.append("Timed out.")
        else:
          parts.append(f"Exit code: {result['return_code']}")
        if result["stdout"]:
          parts.append(f"stdout:\n{result['stdout']}")
        if result["stderr"]:
          parts.append(f"stderr:\n{result['stderr']}")

      _fmt("Original", orig_result)
      parts.append("")
      _fmt("Optimized", opt_result)

      differs = (
        orig_result["return_code"] != opt_result["return_code"]
        or orig_result["stdout"] != opt_result["stdout"]
        or orig_result["timed_out"] != opt_result["timed_out"]
      )

      parts.append("")
      if differs:
        parts.append("Result: MISCOMPILATION DETECTED — outputs differ.")
      else:
        parts.append("Result: OK — outputs match.")

      return "\n".join(parts)
