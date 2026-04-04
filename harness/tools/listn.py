from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class ListNTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl, n: int = 250):
    self.acl = acl
    self.n = n

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "list",
      f"List directory contents (files and subdirectories), sorted alphabetically, returning up to {self.n} entries from a given index. Use this to explore the LLVM source tree structure.",
      [
        FuncToolSpec.Param(
          "directory",
          "string",
          True,
          "The relative path (starting with llvm/) to the directory to list.",
        ),
        FuncToolSpec.Param(
          "k",
          "integer",
          True,
          f"The index to start returning the contents from (1-based index). For example, when k=10, it will return the 10th content and the next {self.n - 1} results.",
        ),
      ],
    )

  def _call(self, *, directory: str, k: int, **kwargs) -> str:
    if k < 1:
      raise FuncToolCallException(
        f"The index k must be a positive integer, but {k} was given."
      )
    k -= 1  # Convert to 0-based index
    dir_full_path = self.acl.check_readable_dir(directory)
    try:
      contents = [path for path in dir_full_path.iterdir()]
      files = [path for path in contents if path.is_file()]
      dirs = [path for path in contents if path.is_dir()]
      results = [str(path.relative_to(self.acl.root)) + "/" for path in dirs] + [
        str(path.relative_to(self.acl.root)) for path in files
      ]
      # Filter out ignored paths.
      results = [r for r in results if not self.acl.is_ignored(r.rstrip("/"))]
      results.sort()  # Sort the results alphabetically
    except Exception as e:
      raise FuncToolCallException(f"Failed to list the directory {directory}. {e}")
    if k >= len(results):
      raise FuncToolCallException(
        f"Index {k + 1} is out of bounds for the contents (total contents: {len(results)})."
      )
    return "\n".join(results[k : k + self.n]) or "The directory is empty."
