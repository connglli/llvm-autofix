from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class WriteTool(FuncToolBase):
  def __init__(self, acl: AccessControl):
    self.acl = acl

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "write",
      "Write content to a file, overwriting it entirely or creating it if it doesn't exist. Use this when you need to create a new file (e.g., a test case) or rewrite a file from scratch. Prefer `edit` for partial modifications.",
      [
        FuncToolSpec.Param(
          "file",
          "string",
          True,
          "The relative path of the file to write (starting with llvm/).",
        ),
        FuncToolSpec.Param(
          "content", "string", True, "The content to write to the file."
        ),
      ],
    )

  def _call(self, *, file: str, content: str, **kwargs) -> str:
    full_path = self.acl.check_editable_file(file, should_exist=False)
    try:
      full_path.parent.mkdir(parents=True, exist_ok=True)
      full_path.write_text(content, encoding="utf-8")
      return f"File {file} written successfully."
    except Exception as e:
      raise FuncToolCallException(f"Failed to write to file {file}. {e}")
