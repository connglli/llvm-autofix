from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


class EditTool(StatelessFuncToolBase):
  def __init__(self, acl: AccessControl):
    self.acl = acl

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "edit",
      "Replace an exact code snippet in a file with new content. Use this when you need to modify specific lines — provide the exact existing text to match and the replacement. Prefer this over `write` for targeted changes.",
      [
        FuncToolSpec.Param(
          "file",
          "string",
          True,
          "The absolute path of the file to edit.",
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
