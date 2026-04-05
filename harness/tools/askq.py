from harness.lms.tool import FuncToolSpec, StatelessFuncToolBase
from harness.utils.console import get_boxed_console


class AskQuestionTool(StatelessFuncToolBase):
  def __init__(self):
    self.console = get_boxed_console(box_title="Agent Question", debug_mode=True)

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "ask",
      "Ask the user multi-choice questions. "
      "Use this tool when you need to ask the user questions during the execution of your task to "
      "clarify requirements, request missing information, get feedback, or offer suggestions. "
      'If you offer a specific option, make that the first option in the list and add "(Recommended)" to indicate.',
      [
        FuncToolSpec.Param(
          "question",
          "string",
          True,
          "The question to ask the user.",
        ),
      ],
    )

  def _call(self, *, question: str, **kwargs) -> str:
    self.console.printb(message=question)
    answer = input("> ")
    return answer
