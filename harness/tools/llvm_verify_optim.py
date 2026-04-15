import re
import shlex
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from harness.llvm.intern.llvm import filter_out_unsupported_feats, is_opt_crash
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase
from harness.tools.llvm_mixins import LlvmBuildDirMixin
from harness.utils.cmdline import spawn_process


class VerifyOptimTool(LlvmBuildDirMixin, StatelessFuncToolBase):
  def __init__(self, llvm_build_dir: str, alive_tv_path: str):
    LlvmBuildDirMixin.__init__(self, llvm_build_dir)
    self._opt = self._binary_path("opt")
    self._alive_tv = Path(alive_tv_path).resolve()
    if not self._alive_tv.is_file():
      raise FuncToolCallException(f"alive-tv not found at {self._alive_tv}")

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "llvm_verify_optim",
      "Verify whether an LLVM optimization pass preserves semantics for a single IR file. "
      "Given an IR file and opt arguments, this tool: "
      "(1) runs opt to produce the optimized IR, and "
      "(2) runs alive2 to formally verify that the optimized IR is a refinement of the original. "
      "Use this to check whether an optimization is semantically correct. "
      "Unlike llvm_check_optim which compares execution results, this uses formal verification (SMT solving) "
      "and can catch bugs that specific test inputs might miss.",
      [
        FuncToolSpec.Param(
          "input_path",
          "string",
          True,
          "Path to the LLVM IR file to verify. Example: '/tmp/input.ll'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          True,
          "Arguments for opt to specify the optimization pass. "
          "Example: '-S -passes=instcombine'.",
        ),
        FuncToolSpec.Param(
          "alive2_args",
          "string",
          False,
          "Optional arguments passed to alive-tv. "
          "Recommended: '--disable-undef-input --smt-to=60000'.",
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

  def _verify(self, src_path: Path, tgt_path: Path, args: str) -> str:
    """Run alive2 on src -> tgt. Returns the formatted result."""
    src_code = filter_out_unsupported_feats(src_path.read_text(encoding="utf-8"))
    tgt_code = filter_out_unsupported_feats(tgt_path.read_text(encoding="utf-8"))

    with TemporaryDirectory() as tmpdir:
      filtered_src = Path(tmpdir) / "src.ll"
      filtered_tgt = Path(tmpdir) / "tgt.ll"
      filtered_src.write_text(src_code, encoding="utf-8")
      filtered_tgt.write_text(tgt_code, encoding="utf-8")
      proc = spawn_process(
        shlex.split(f"{self._alive_tv} {args.strip()} {filtered_src} {filtered_tgt}"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
      )

    out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
      raise FuncToolCallException(f"alive-tv failed to run: {out}")

    correct = (
      "0 incorrect transformations" in out
      and "0 failed-to-prove transformations" in out
      and "0 Alive2 errors" in out
    )
    m = re.search(r"(\d+) incorrect transformations", out)
    n_incorrect = int(m.group(1)) if m else 0

    if correct:
      return f"Transformation is correct.\n\n{out}"
    if n_incorrect > 0:
      return (
        f"Transformation is INCORRECT "
        f"({n_incorrect} incorrect transformation(s) found).\n\n{out}"
      )
    return f"Verification inconclusive (failed-to-prove or Alive2 errors).\n\n{out}"

  def _call(
    self,
    *,
    input_path: str,
    args: str,
    alive2_args: str = "",
    **kwargs,
  ) -> str:
    input_file = Path(input_path)
    if not input_file.is_file():
      raise FuncToolCallException(f"Input file not found: {input_path}")

    with TemporaryDirectory() as tmpdir:
      opt_path = Path(tmpdir) / "optimized.ll"
      self._optimize(input_file, args, opt_path)
      return self._verify(input_file, opt_path, alive2_args)
