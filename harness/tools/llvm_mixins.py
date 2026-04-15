from pathlib import Path

from harness.lms.tool import FuncToolCallException


class LlvmBuildDirMixin:
  """Mixin for tools that invoke binaries from an LLVM build directory.

  Binary paths are resolved eagerly but validated lazily — ``_binary_path``
  records which binaries the tool needs, and ``_check`` validates they exist
  before each call.  This lets the harness always register these tools so the
  agent can see them; if LLVM hasn't been built yet the agent gets an
  actionable error telling it to run ``llvm_build``.
  """

  def __init__(self, llvm_build_dir: str):
    self.llvm_build_dir = Path(llvm_build_dir).resolve()
    self._required_binaries: dict[str, Path] = {}

  def _binary_path(self, name: str) -> Path:
    p = self.llvm_build_dir / "bin" / name
    self._required_binaries[name] = p
    return p

  def _check(self, **kwargs):
    super()._check(**kwargs)
    if not self.llvm_build_dir.is_dir():
      raise FuncToolCallException(
        f"LLVM build directory not found: {self.llvm_build_dir}. "
        "Build LLVM first using llvm_build."
      )
    for name, path in self._required_binaries.items():
      if not path.is_file():
        raise FuncToolCallException(
          f"{name} not found at {path}. Build LLVM first using llvm_build."
        )
