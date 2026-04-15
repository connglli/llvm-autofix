import re
import shlex
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from harness.llvm.intern.llvm import filter_out_unsupported_feats
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase
from harness.utils.cmdline import spawn_process


class VerifyIrTool(StatelessFuncToolBase):
  def __init__(self, alive_tv_path: str):
    self._alive_tv = Path(alive_tv_path).resolve()
    if not self._alive_tv.is_file():
      raise FuncToolCallException(f"alive-tv not found at {self._alive_tv}")

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "llvm_verify_ir",
      "Check whether a transformation from one LLVM IR to another is semantically correct "
      "(i.e., the target IR is a refinement of the source). "
      "Reports incorrect transformations with a counterexample if found. "
      "This is the alive2 tool, which performs formal verification based on SMT solving. "
      "Use the llvm_optimize_ir tool first to produce the transformed IR file if needed.",
      [
        FuncToolSpec.Param(
          "src_path",
          "string",
          True,
          "Path to the original (source) LLVM IR file before the transformation. "
          "Example: '/tmp/src.ll'.",
        ),
        FuncToolSpec.Param(
          "tgt_path",
          "string",
          True,
          "Path to the transformed (target) LLVM IR file after the transformation. "
          "Example: '/tmp/tgt.ll'.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          False,
          "Optional arguments passed to alive-tv. "
          "Recommended: '--disable-undef-input --smt-to=60000'.",
        ),
      ],
      keywords=["alive2", "alive", "verify", "smt", "refinement", "correctness", "ir"],
    )

  def _call(self, *, src_path: str, tgt_path: str, args: str = "", **kwargs) -> str:
    src_file = Path(src_path)
    tgt_file = Path(tgt_path)
    for name, f in (("src_path", src_file), ("tgt_path", tgt_file)):
      if not f.is_file():
        raise FuncToolCallException(f"File not found for {name}: {f}")

    src_code = filter_out_unsupported_feats(src_file.read_text(encoding="utf-8"))
    tgt_code = filter_out_unsupported_feats(tgt_file.read_text(encoding="utf-8"))

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
      return f"Transformation is INCORRECT ({n_incorrect} incorrect transformation(s) found).\n\n{out}"
    return f"Verification inconclusive (failed-to-prove or Alive2 errors).\n\n{out}"
