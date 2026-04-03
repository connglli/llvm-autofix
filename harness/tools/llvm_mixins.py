from pathlib import Path

from harness.lms.tool import FuncToolCallException


class LlvmBuildDirMixin:
  """Mixin for tools that invoke binaries from an LLVM build directory.

  Requires a completed LLVM build at llvm_build_dir. Instantiation will fail
  if the requested binary does not exist (i.e., LLVM has not been built yet).
  """

  def __init__(self, llvm_build_dir: str):
    self.llvm_build_dir = Path(llvm_build_dir).resolve()
    if not self.llvm_build_dir.is_dir():
      raise FuncToolCallException(
        f"LLVM build directory not found: {self.llvm_build_dir}"
      )

  def _binary_path(self, name: str) -> Path:
    p = self.llvm_build_dir / "bin" / name
    if not p.is_file():
      raise FuncToolCallException(f"{name} not found at {p}")
    return p
