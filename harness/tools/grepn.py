from subprocess import CalledProcessError

from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase
from harness.utils import cmdline


class GrepNTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl, n: int = 250):
    self.acl = acl
    self.n = n

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "grep",
      f"Search file contents for a pattern using grep. Returns up to {self.n} matching lines sorted alphabetically from a given index. Prefer `ripgrep` for faster regex searches.",
      [
        FuncToolSpec.Param(
          "k",
          "integer",
          True,
          f"The index to start returning the results from (1-based index). For example, when k=10, it will return the 10th result and the next {self.n - 1} results.",
        ),
        FuncToolSpec.Param(
          "args",
          "string",
          True,
          "The arguments including options, patterns, and files. NOTICE: ensure the pattern to search is wrapped in single quotes (i.e., '...'), e.g., `-nRI 'test-pattern'`.",
        ),
        FuncToolSpec.Param(
          "directory",
          "string",
          True,
          "The absolute path to the base directory to search in.",
        ),
      ],
    )

  def _call(self, *, k: int, args: str, directory: str, **kwargs) -> str:
    if k < 1:
      raise FuncToolCallException(
        f"The index k must be a positive integer, but {k} was given."
      )
    if not args:
      raise FuncToolCallException(
        "No arguments provided. Please specify the pattern and files to search."
      )
    search_dir = self.acl.check_readable_dir(directory)
    try:
      result = cmdline.check_output(f"grep {args}", cwd=search_dir)
      lines = result.decode("utf-8").strip().splitlines(keepends=True)
    except CalledProcessError as e:
      if e.returncode == 1:
        return "No matches found."
      raise FuncToolCallException(
        f"{e.stdout.decode('utf-8').strip() if e.stdout else str(e)}"
      )
    if not lines:
      return "No matches found."
    lines.sort()  # Sort the results alphabetically
    k -= 1  # Convert to 0-based index
    if k >= len(lines):
      raise FuncToolCallException(
        f"Index {k + 1} is out of bounds for the results (total results: {len(lines)})."
      )
    selected = lines[k : k + self.n]
    return "".join(selected)  # Return the selected lines as a single string
