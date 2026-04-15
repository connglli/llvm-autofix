"""SubAgentTool — spawn a stateless sub-agent to accomplish a focused task."""

from __future__ import annotations

from typing import Optional

from harness.lms.agent import AgentBase
from harness.lms.tool import TOOL_SEARCH_NAME, FuncToolSpec, StatelessFuncToolBase


class AgentDoneTool(StatelessFuncToolBase):
  """Special tool that signals sub-agent completion and returns a result."""

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "agent_done",
      "Signal that the task is complete and return the result to the calling agent.",
      [
        FuncToolSpec.Param(
          "result",
          "string",
          True,
          "The final result text to return from this sub-agent.",
        ),
      ],
      keywords=["agent", "done", "complete", "result"],
    )

  def _call(self, *, result: str, **kwargs) -> str:
    return result


class SubAgentTool(StatelessFuncToolBase):
  """Spawn a stateless sub-agent to accomplish a focused task.

  The sub-agent starts with a clean context (no inherited history),
  uses the same model configuration as the calling agent, and is
  equipped with a subset of tools/skills chosen at call time.
  """

  def __init__(self, agent: AgentBase):
    self.agent = agent

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "subagent",
      (
        "Spawn a new sub-agent to accomplish a task. The sub-agent starts with "
        "a fresh, empty context (no history from the current conversation) and "
        "uses the same model. Use this to offload focused sub-tasks and keep "
        "the current context clean. The sub-agent must call `agent_done` to "
        "return its result."
      ),
      [
        FuncToolSpec.Param(
          "task",
          "string",
          True,
          "A clear, self-contained description of the task for the sub-agent. "
          "Include all necessary context — the sub-agent has no prior history.",
        ),
        FuncToolSpec.Param(
          "tools",
          "string",
          False,
          "Comma-separated list of tool/skill names the sub-agent should have "
          "access to (e.g. 'read,find,ripgrep,llvm-patchreview'). If omitted, "
          "all tools and skills from the calling agent are available (except "
          "this agent tool itself).",
        ),
      ],
      keywords=["subagent", "spawn", "delegate", "parallel"],
    )

  def _call(
    self,
    *,
    task: str,
    tools: Optional[str] = None,
    **kwargs,
  ) -> str:
    from harness.lms.agent import AgentHooks
    from harness.lms.meter import ReachRoundLimit, ReachTokenLimit
    from harness.lms.skill import SkillTool
    from harness.lms.tool import DeferredToolWrapper

    # Resolve tool names (skip parent's tool_search — sub gets its own)
    if tools is not None:
      tool_names = [
        t.strip()
        for t in tools.split(",")
        if t.strip() and t.strip() != TOOL_SEARCH_NAME
      ]
    else:
      tool_names = [
        name
        for name in self.agent.tools.list()
        if not isinstance(self.agent.tools.get(name), SubAgentTool)
        and name != TOOL_SEARCH_NAME
      ]

    # Create sub-agent (no history)
    sub = self.agent.config.create_agent()

    # Register requested tools and skills (fresh instances, skills rebound).
    # Deferred tools are re-registered with deferred=True so the sub-agent
    # gets its own tool_search.
    # Each tool inherits the parent's remaining budget. The post_tool_call
    # hook keeps the parent's budget in sync by decrementing it on each call.
    # TODO: This assumes sequential execution — only one sub-agent runs at a
    # time. If parallel tool calls are supported in the future, multiple
    # sub-agents would each snapshot the same remaining budget at spawn time,
    # leading to over-consumption (TOCTOU — time-of-check-time-of-us). A
    # shared budget counter or reservation mechanism would be needed.
    missing = []
    for name in tool_names:
      if self.agent.tools.has(name):
        tool_obj = self.agent.tools.get(name)
        is_deferred = isinstance(tool_obj, DeferredToolWrapper)
        if isinstance(tool_obj, SkillTool):
          tool_obj = tool_obj.for_agent(sub)
        else:
          tool_obj = tool_obj.fresh()
        budget = self.agent.tools.get_remaining_budget(name)
        sub.register_tool(tool_obj, budget, deferred=is_deferred)
      else:
        missing.append(name)

    if missing:
      sub.console.print(
        f"Warning: not available in parent agent: {missing}",
        color="yellow",
      )

    # Register the done tool
    sub.register_tool(AgentDoneTool(), 1)

    # Seed the sub-agent with the task
    sub.append_user_message(task)

    # Run sub-agent loop
    done_result = [None]

    def post_response(_: str):
      return True, "Please continue. Call the `agent_done` tool when finished."

    parent_tools = self.agent.tools

    def post_tool_call(name: str, _: str, result: str):
      if name == "agent_done":
        done_result[0] = result
        return False, result
      # Keep the parent's budget in sync.
      if parent_tools.has(name):
        parent_tools.consume_budget(name)
      return True, result

    try:
      sub.run(
        AgentHooks(post_response=post_response, post_tool_call=post_tool_call),
      )
    except (ReachRoundLimit, ReachTokenLimit):
      pass

    result = done_result[0]
    if result is None:
      result = "Error: sub-agent exhausted its budget without producing a result."

    return result
