from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class EditTool(FuncToolBase):
  def __init__(self, acl: AccessControl):
    self.acl = acl

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "edit",
      "Edit a file to replace text within a file with new text.",
      [
        FuncToolSpec.Param(
          "file",
          "string",
          True,
          "The relative path of the file to edit (starting with llvm/).",
        ),
        FuncToolSpec.Param(
          "old", "string", True, "The *exact* code snippet to be replaced in the file."
        ),
        FuncToolSpec.Param("new", "string", True, "The new code snippet."),
      ],
    )

  def _call(self, *, file: str, old: str, new: str, **kwargs) -> str:
    full_path = self.acl.check_editable_file(file)
    content = full_path.read_text(encoding="utf-8")
    if old not in content:
      raise FuncToolCallException("The `old` text is not found in file.")
    content = content.replace(old, new)
    full_path.write_text(content, encoding="utf-8")
    return "Replaced successfully."
