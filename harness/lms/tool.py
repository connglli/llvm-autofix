import json
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Optional

from harness.utils.bm25 import BM25Index


class FuncToolSpec:
  @dataclass
  class Param:
    name: str  # Name of the parameter
    type: str  # Type of the parameter (e.g., "string", "integer", "list[integer]" etc.)
    req: bool  # Whether the parameter is required
    desc: str  # Description of the parameter

  def __init__(
    self,
    name: str,
    desc: str,
    parameters: List[Param],
    keywords: List[str],
  ):
    self.name = name
    self.desc = desc
    self.params = parameters
    self.keywords = keywords

  def render_in_claude_format(self) -> dict:
    return {
      "name": self.name,
      "description": self.desc,
      "input_schema": {
        "type": "object",
        "properties": {
          p.name: {"type": p.type, "description": p.desc} for p in self.params
        },
        "required": [p.name for p in self.params if p.req],
        "additionalProperties": False,
      },
    }

  def render_in_openai_format(self) -> dict:
    return {
      "type": "function",
      "function": {
        "name": self.name,
        "description": self.desc,
        "parameters": {
          "type": "object",
          "properties": {
            p.name: {"type": p.type, "description": p.desc} for p in self.params
          },
          "required": [p.name for p in self.params if p.req],
          "additionalProperties": False,
        },
      },
    }

  def render_in_simple_format(self) -> dict:
    return {
      "name": self.name,
      "description": self.desc,
      "parameters": {
        p.name: {"type": p.type, "required": p.req, "description": p.desc}
        for p in self.params
      },
    }


class FuncToolCallException(Exception):
  pass


class FuncToolBase(ABC):
  def name(self) -> str:
    """The unique name of the tool"""
    return self.spec().name

  def desc(self) -> str:
    return self.spec().desc

  @abstractmethod
  def spec(self) -> FuncToolSpec:
    """
    Return the specification of this tool.
    """
    ...

  @abstractmethod
  def fresh(self) -> "FuncToolBase":
    """
    Return a new instance with clean state for use in a new context (e.g. skill sub-loop).
    Every tool must implement this and must return a new instance with all mutable state reset.
    Prefer :class:`StatelessFuncToolBase` or :class:`StatefulFuncToolBase`
    which provide the correct default.
    """
    ...

  def call(self, **kwargs) -> str:
    """
    Run the tool using the given arguments.
    Return the result of the tool call as a string if successful.
    Otherwise, raise a FuncToolCallException.
    """
    self._check(**kwargs)
    return self._call(**kwargs)

  def _check(self, **kwargs):
    """
    Check if the tool can be called with the given arguments.
    Raise a FuncToolCallException if there are any issues.
    """
    # Check if all required parameters are present
    required_params = [p.name for p in self.spec().params if p.req]
    missing_params = [p for p in required_params if p not in kwargs]
    if missing_params:
      raise FuncToolCallException(
        f"The following required parameters are missing: {', '.join(missing_params)}"
      )
    return None  # By default, only check for required parameters

  @abstractmethod
  def _call(self, **kwargs) -> str:
    """
    Run the tool using the given arguments.
    Return the result of the tool call as a string if successful.
    Otherwise, raise a FuncToolCallException.
    """
    ...


class StatelessFuncToolBase(FuncToolBase):
  """Base class for tools that hold no mutable state between calls."""

  def fresh(self) -> "StatelessFuncToolBase":
    return self  # Stateless tools can return themselves since they hold no state


class StatefulFuncToolBase(FuncToolBase):
  """
  Base class for tools that hold mutable state between calls.
  Subclasses must implement :meth:`fresh` to return a new instance with
  all mutable state reset (e.g. ``return TodoTool()``).
  """

  @abstractmethod
  def fresh(self) -> "StatefulFuncToolBase": ...


_DEFERRED_STUB = "[deferred] {stub}"
_DEFERRED_STUB_LEN = 32


class DeferredToolWrapper(FuncToolBase):
  """Wraps a tool so the LLM schema shows a stub description.

  The tool is fully callable — only ``spec()`` is altered to truncate the
  description.  This lets the existing rendering pipeline work unchanged:
  the LLM sees the tool name, its params, and a short stub, but needs
  ``tool_search(action="load")`` to read the full description.
  """

  def __init__(self, tool: FuncToolBase):
    self._tool = tool

  def spec(self) -> FuncToolSpec:
    real = self._tool.spec()
    stub = real.desc[:_DEFERRED_STUB_LEN]
    if len(real.desc) > _DEFERRED_STUB_LEN:
      stub += "..."
    return FuncToolSpec(
      real.name,
      _DEFERRED_STUB.format(stub=stub),
      [],  # Hide all parameters
      real.keywords,
    )

  def real_spec(self) -> FuncToolSpec:
    """Return the original, un-stubbed spec."""
    return self._tool.spec()

  def fresh(self) -> FuncToolBase:
    """Unwrap on fresh — subagents get the real tool with full description."""
    return self._tool.fresh()

  def _call(self, **kwargs) -> str:
    return self._tool._call(**kwargs)

  def _check(self, **kwargs):
    return self._tool._check(**kwargs)


TOOL_SEARCH_NAME = "tool_search"


class ToolSearchTool(StatelessFuncToolBase):
  """Meta-tool that lets the agent discover and inspect deferred tools.

  Deferred tools are registered in the LLM schema with stub descriptions.
  This tool allows the agent to list them, search by keyword (BM25-ranked),
  and load full descriptions before calling.
  """

  def __init__(self, deferred_tools: list[FuncToolBase]):
    self._tools = {t.name(): t for t in deferred_tools}
    corpus = {}
    for t in deferred_tools:
      s = t.spec()
      text = f"{s.name} {s.desc} {' '.join(s.keywords)}"
      corpus[s.name] = text
    self._index = BM25Index(corpus)

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      TOOL_SEARCH_NAME,
      "Discover and inspect available tools. "
      "Some tools have deferred descriptions — use this to see their full spec before calling. "
      "Actions: 'list' shows all deferred tools, 'search' finds tools by keyword (BM25-ranked), "
      "'load' returns the full description and parameters of a specific tool.",
      [
        FuncToolSpec.Param(
          "action",
          "string",
          True,
          "The action to perform: 'list', 'search', or 'load'.",
        ),
        FuncToolSpec.Param(
          "query",
          "string",
          False,
          "Required when action is 'search'. Keywords to search for.",
        ),
        FuncToolSpec.Param(
          "name",
          "string",
          False,
          "Required when action is 'load'. The exact name of the tool to load.",
        ),
      ],
      keywords=["tool", "search", "find", "discover", "deferred", "load", "list"],
    )

  def _call(
    self,
    *,
    action: str,
    query: str = "",
    name: str = "",
    **kwargs,
  ) -> str:
    if action == "list":
      return self._do_list()
    elif action == "search":
      if not query:
        raise FuncToolCallException(
          "The 'query' parameter is required when action is 'search'."
        )
      return self._do_search(query)
    elif action == "load":
      if not name:
        raise FuncToolCallException(
          "The 'name' parameter is required when action is 'load'."
        )
      return self._do_load(name)
    else:
      raise FuncToolCallException(
        f"Invalid action '{action}'. Must be 'list', 'search', or 'load'."
      )

  def _do_list(self) -> str:
    if not self._tools:
      return "No deferred tools available."
    lines = []
    for t in self._tools.values():
      s = t.spec()
      desc = s.desc[:60] + "..." if len(s.desc) > 60 else s.desc
      lines.append(f"- {s.name}: {desc}")
    return "\n".join(lines)

  def _do_search(self, query: str) -> str:
    results = self._index.query(query, top_k=5)
    if not results:
      return f"No tools matched the query '{query}'."
    lines = []
    for name, score in results:
      s = self._tools[name].spec()
      lines.append(f"- {s.name} (score: {score:.2f}): {s.desc}")
    return "\n".join(lines)

  def _do_load(self, name: str) -> str:
    if name not in self._tools:
      available = ", ".join(sorted(self._tools.keys()))
      raise FuncToolCallException(
        f"Tool '{name}' is not a deferred tool. Available: {available}"
      )

    return json.dumps(
      self._tools[name].spec().render_in_simple_format(),
      indent=2,
      ensure_ascii=False,
    )


class ToolRegistry:
  def __init__(self):
    self.tools = OrderedDict()
    self._deferred_tools: list[FuncToolBase] = []

  def copy(self) -> "ToolRegistry":
    registry = ToolRegistry()
    for name, (tool, _, total_budget) in self.tools.items():
      registry.tools[name] = [tool, total_budget, total_budget]
    registry._deferred_tools = list(self._deferred_tools)
    return registry

  def register(
    self,
    tool: FuncToolBase,
    budget: Optional[int] = None,
    deferred: bool = False,
  ):
    if tool.name() in self.tools:
      raise ValueError(f"Tool with name {tool.name()} is already registered.")
    if deferred:
      self._deferred_tools.append(tool)
      wrapped = DeferredToolWrapper(tool)
      self.tools[wrapped.name()] = [wrapped, budget, budget]
      self._rebuild_tool_search(budget)
    else:
      self.tools[tool.name()] = [tool, budget, budget]

  def _rebuild_tool_search(self, budget: Optional[int] = None):
    """Create or rebuild the tool_search tool from accumulated deferred tools."""
    tool_search = ToolSearchTool(self._deferred_tools)
    if TOOL_SEARCH_NAME in self.tools:
      # Preserve existing budget
      _, remaining, total = self.tools[TOOL_SEARCH_NAME]
      self.tools[TOOL_SEARCH_NAME] = [tool_search, remaining, total]
    else:
      self.tools[TOOL_SEARCH_NAME] = [tool_search, budget, budget]

  def has(self, name: str, ignore_budget=True) -> bool:
    return (
      name in self.tools if ignore_budget else name in self.list(ignore_budget=False)
    )

  def has_deferred_tools(self) -> bool:
    return len(self._deferred_tools) > 0

  def get(self, name: str) -> FuncToolBase:
    self._ensure_registered(name)
    return self.tools[name][0]

  def get_remaining_budget(self, name: str) -> Optional[int]:
    self._ensure_registered(name)
    return self.tools[name][1]

  def get_total_budget(self, name: str) -> Optional[int]:
    self._ensure_registered(name)
    return self.tools[name][2]

  @staticmethod
  def format_budget(budget: Optional[int]) -> str:
    return "<unlimited>" if budget is None else str(budget)

  def list(self, ignore_budget=True) -> List[str]:
    if ignore_budget:
      return list(self.tools.keys())
    else:
      return [
        name
        for name in self.tools
        if self.tools[name][1] is None or self.tools[name][1] > 0
      ]

  def call(self, name: str, args: dict) -> str:
    try:
      self._ensure_remaining_budget(name)
      result = self.tools[name][0].call(**args)
    except FuncToolCallException as e:
      result = f"Error: {e}"
    except Exception as e:
      result = f"Error: {e}"
    finally:
      if name in self.tools and self.tools[name][1] is not None:
        self.tools[name][1] -= 1
    result = result.strip()
    if result == "":
      result = "Success: <No output>"
    return result

  def consume_budget(self, name: str):
    """Decrement the remaining budget for a tool by one (no tool execution)."""
    self._ensure_registered(name)
    if self.tools[name][1] is not None and self.tools[name][1] > 0:
      self.tools[name][1] -= 1

  def _ensure_remaining_budget(self, name: str):
    self._ensure_registered(name)
    if self.tools[name][1] is not None and self.tools[name][1] <= 0:
      raise FuncToolCallException(f"Tool {name} has no remaining budget left.")

  def _ensure_registered(self, name: str):
    if name not in self.tools:
      raise FuncToolCallException(f"Tool {name} is not available.")
