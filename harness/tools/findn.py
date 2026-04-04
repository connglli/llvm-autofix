import glob

from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class FindNTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl, n: int = 250):
    self.acl = acl
    self.n = n

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "find",
      f"Find files matching a glob pattern (e.g., `**/*.cpp`, `*.h`) within a directory. Use this to locate source files, headers, or test files by name pattern. Returns up to {self.n} results sorted alphabetically from a given index.",
      [
        FuncToolSpec.Param(
          "k",
          "integer",
          True,
          f"The index to start returning the results from (1-based index). For example, when k=10, it will return the 10th result and the next {self.n - 1} results.",
        ),
        FuncToolSpec.Param("pattern", "string", True, "The pattern of the files."),
        FuncToolSpec.Param(
          "directory",
          "string",
          True,
          "Find files in this directory (a relative path starting with llvm/).",
        ),
      ],
    )

  def _call(self, *, k: int, pattern: str, directory: str, **kwargs) -> str:
    if k < 1:
      raise FuncToolCallException(
        f"The index k must be a positive integer, but {k} was given."
      )
    dir_full_path = self.acl.check_readable_dir(directory)
    try:
      results = glob.glob(pattern, root_dir=dir_full_path, recursive=True)
    except Exception as e:
      raise FuncToolCallException(f"Failed to find files with pattern {pattern}. {e}")
    if not results:
      return f"No files found matching the pattern {pattern}."
    results = [f"{path}" for path in results if (dir_full_path / path).is_file()]
    # Filter out ignored paths.
    results = [
      r for r in results if not self.acl.is_ignored(f"{directory.rstrip('/')}/{r}")
    ]
    results.sort()  # Sort the results alphabetically
    k -= 1  # Convert to 0-based index
    if k >= len(results):
      raise FuncToolCallException(
        f"Index {k + 1} is out of bounds for the results (total results: {len(results)})."
      )
    selected = results[k : k + self.n]
    return "\n".join(selected)  # Return the selected files as a single string
