from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class ReadNTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl, n: int = 250):
    self.acl = acl
    self.n = n

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "read",
      f"Read up to {self.n} lines from a file starting at a given line number. Use this to inspect source code, headers, or any text file in the LLVM tree.",
      [
        FuncToolSpec.Param(
          "file",
          "string",
          True,
          "The relative path to the file to read. The path should start with llvm/.",
        ),
        FuncToolSpec.Param(
          "position",
          "integer",
          True,
          "The line number to start reading from (1-based index).",
        ),
      ],
    )

  def _call(self, *, file: str, position: int, **kwargs) -> str:
    if position < 1:
      raise FuncToolCallException(
        f"Position must be a positive integer, but {position} was given."
      )
    file_full_path = self.acl.check_readable_file(file)
    try:
      lines = file_full_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception as e:
      raise FuncToolCallException(f"Failed to read the file {file}. {e}")
    start_pos = position - 1  # Convert to 0-based index
    if start_pos >= len(lines):
      raise FuncToolCallException(
        f"Position {position} is out of bounds for the file {file} (total lines: {len(lines)})."
      )
    end_pos = min(start_pos + self.n, len(lines))
    selected = lines[start_pos:end_pos]
    header = f"file: {file}:{position}-{end_pos + 1}\n"
    separator = "-" * (len(header) - 1)
    lno_fmt = "{:>" + str(len(str(end_pos + 1))) + "}"
    return (
      header
      + separator
      + "\n"
      + "".join(
        [
          lno_fmt.format(lno + position) + " " + line
          for lno, line in enumerate(selected)
        ]
      )
      + separator
    )
