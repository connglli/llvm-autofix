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


class LlvmSourceMixin:
  def check_llvm_dir(self, subdir: str, should_exist=True) -> Path:
    """
    Check if the given directory is a subdirectory of the llvm/ directory.
    Raises FuncToolCallException if the directory is not valid.
    """
    if not subdir.startswith("llvm"):
      raise FuncToolCallException(
        "The directory path must start with llvm/. Please provide a valid relative path."
      )
    full_path = (self.llvm_dir / subdir).resolve().absolute()
    if not full_path.is_relative_to(self.llvm_dir / "llvm"):
      raise FuncToolCallException(
        "The directory path must be relative to the llvm/ directory. Please provide a valid relative path."
      )
    if not should_exist:
      return full_path
    if not full_path.exists():
      raise FuncToolCallException(f"The directory {subdir} does not exist.")
    if not full_path.is_dir():
      raise FuncToolCallException(f"The path {subdir} is not a directory.")
    return full_path

  def check_llvm_file(self, file: str, should_exist=True) -> Path:
    """
    Check if the given file is a valid file in the llvm directory.
    Raises FuncToolCallException if the file is not valid.
    """
    if not file.startswith("llvm"):
      raise FuncToolCallException(
        "The file path must start with llvm/. Please provide a valid relative path."
      )
    full_path = (self.llvm_dir / file).resolve().absolute()
    if not full_path.is_relative_to(self.llvm_dir / "llvm"):
      raise FuncToolCallException(
        "The file path must be relative to the llvm/ directory. Please provide a valid relative path."
      )
    if not should_exist:
      return full_path
    if not full_path.exists():
      raise FuncToolCallException(f"The file {file} does not exist.")
    if not full_path.is_file():
      raise FuncToolCallException(f"The path {file} is not a file.")
    return full_path  # Return the resolved path for further use
