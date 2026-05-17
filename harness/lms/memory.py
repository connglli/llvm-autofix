"""Working-memory compaction for long agent chat histories.

A long-running agent grows its ``history`` until the next request would
approach the model's context window. :class:`MemoryCompactor` summarizes
the conversation into a single self-contained note that another agent
(same driver, same config) can continue the task from.

This class is pure: it does not mutate the input history, does not own
the agent, does not decide where the summary goes. Its only job is
``history → summary string``. The caller (typically
:meth:`AgentBase.maybe_compact_history`) decides how to splice that
summary back into a new history shape.

Triggering: :meth:`should_compact` estimates the next request size from
(a) the exact token counts the driver's last API response reported, plus
(b) a 0.3-tokens-per-character estimate of the latest tool result (which
the previous API call had not yet seen). When the estimate exceeds the
configured threshold, the caller invokes :meth:`compact`.
"""

from __future__ import annotations

import dataclasses
from typing import List

from harness.lms.agent import AgentConfig, AgentHooks
from harness.lms.message import (
  ChatMessage,
  ChatMessageFunctionCall,
  ChatMessageFunctionCallOutput,
  ChatMessageMessage,
)
from harness.lms.meter import TokenUsage
from harness.lms.tool import (
  FuncToolCallException,
  FuncToolSpec,
  StatelessFuncToolBase,
)


class MemoryCompactionException(Exception):
  pass


# Tool the summarizer sub-agent uses to hand its summary back to the
# parent. Mirrors the closure-captured-list pattern used by
# ``autofix.autored._SubmitReproducerTool``.
class _SubmitTool(StatelessFuncToolBase):
  """Captures the compacted working-memory note the summarizer produces."""

  def __init__(self, captured: list):
    self._captured = captured

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "submit",
      "Submit the compacted working-memory note. Call this EXACTLY ONCE "
      "with the full note as the ``summary`` argument; the agent will "
      "exit immediately after a successful call.",
      [
        FuncToolSpec.Param(
          "summary",
          "string",
          True,
          "The full compacted working-memory note. Must follow the "
          "structure specified in the system prompt verbatim.",
        ),
      ],
      [],
    )

  def _call(self, *, summary: str, **_) -> str:
    if not summary or not summary.strip():
      raise FuncToolCallException("summary must not be empty")
    self._captured.append(summary.strip())
    return "Submitted."


class MemoryCompactor:
  """Auto-compaction of agent chat histories via a summarizer sub-agent.

  The sub-agent inherits the parent's driver/model/config but with
  ``enable_memory_compaction=False`` so it cannot recursively compact
  itself. The parent's history is shallow-copied into the sub-agent so
  the sub-agent reads the full conversation context, then a single
  instruction message asks it to call ``submit``.
  """

  # Approximate cl100k_base-style ratio for English text — used to estimate
  # the token cost of the latest tool result before sending it.
  TOKENS_PER_CHAR = 0.3

  SYSTEM_PROMPT = (
    "You are a memory-compaction assistant for a long-running coding agent. "
    "The conversation log above is the agent's working memory. Produce a "
    "structured note that lets another agent (with the same tools) continue "
    "the task from a clean context. The note will REPLACE the bulky middle "
    "of the agent's history; only the last tool call and its result will "
    "be appended after your note verbatim.\n\n"
    "Call `submit(summary=<summary>)` exactly once with `summary` the only "
    "argument. For <summary>, organize it following the structure below — "
    "The next agent reads the note as input, so structure with headings, "
    "bullets, and fenced code blocks where they help. Preserve IR snippets, "
    "backtraces, command lines, and file/line references inside fenced "
    "code blocks so they survive verbatim.\n\n"
    "# Format\n\n"
    "The <summary> must contain these sections, in this order:\n\n"
    "- Original task(s): copy VERBATIM every instruction the user has given "
    "  in the conversation. Users may have appended multiple instructions, "
    "  follow-ups, and clarifications across several user messages — include "
    "  ALL of them, word for word, with their IR snippets, backtraces, file "
    "  paths, line numbers, and any other detail intact. This is "
    "  load-bearing; do NOT paraphrase.\n"
    "- Key facts established: bullet list of confirmed facts about the task "
    "  and the code under investigation.\n"
    "- Hypotheses tried and ruled out: bullet list, each with the concrete "
    "  result that ruled it out.\n"
    "- Current hypothesis or open question: one short paragraph.\n"
    "- Files, symbols, line numbers under investigation: bullet list.\n"
    "- Immediate next action: one sentence describing what the next agent "
    "  should do first.\n\n"
    "# Rules\n\n"
    "1. Do not chat. Do not explain.\n"
    "2. Do not include the tool list and tool call instructions in the "
    "summary. The next agent will be provided the same tools explicitly.\n"
    "3. Think twice and call `submit` once and exit."
  )

  _INSTRUCTION_MESSAGE = (
    "Per the system prompt, summarize the conversation log above into the "
    "structured working-memory note and submit it via `submit`."
  )

  _CHAT_RETRY_NUDGE = (
    "You replied with a chat response, but I need you to call the `submit` "
    "tool with your structured note as the ``summary`` argument `<summary>`. "
    "Please call `submit` now instead of replying conversationally."
  )

  def __init__(self, agent_config: AgentConfig, threshold_tokens: int):
    self.agent_config = agent_config
    self.threshold_tokens = threshold_tokens

  # -------------------------------------------------------------------
  # Trigger
  # -------------------------------------------------------------------

  def should_compact(
    self,
    history: List[ChatMessage],
    last_round_usage: TokenUsage,
  ) -> bool:
    """True iff the next request is estimated to exceed the threshold.

    Hard precondition: the history must end with a user-side message
    (user/system text or a tool result) — compacting after an assistant
    turn would orphan a dangling tool call or drop text the driver is
    about to act on. Asserted (not silently skipped) so a caller that
    violates the contract fails loudly instead of silently missing the
    compaction window.

    The latest user-side message is the one piece of input the previous
    API call did not yet see, so we add its estimated token cost on top
    of the last round's reported usage when deciding whether to compact.
    """
    if self.threshold_tokens <= 0 or not history:
      return False
    last = history[-1]
    if not last.is_from_user():
      raise MemoryCompactionException(
        "History must end with a user-side message (user/system text or tool "
        "result) to be eligible for compaction. The input history ends with a "
        "%s message." % last.type
      )
    if isinstance(last, ChatMessageFunctionCallOutput):
      new_text = last.output
    elif isinstance(last, ChatMessageMessage):
      new_text = last.content
    else:
      raise MemoryCompactionException(f"Unexpected message type: {type(last)}")
    new_tokens = int(len(new_text) * self.TOKENS_PER_CHAR)
    estimated = last_round_usage.total_tokens + new_tokens
    return estimated > self.threshold_tokens

  # -------------------------------------------------------------------
  # Compact
  # -------------------------------------------------------------------

  def compact(self, history: List[ChatMessage]) -> str:
    """Return a compacted summary of *history* as a single text block.

    Spins up a summarizer sub-agent (same driver/model as the parent but
    with ``enable_memory_compaction=False`` so it cannot recursively
    compact itself), seeded with exactly two messages:

    * ``system`` — :attr:`SYSTEM_PROMPT`, the compactor's job description.
    * ``user``   — the parent's history rendered as a plain-text transcript
      followed by :attr:`_INSTRUCTION_MESSAGE`. Bundling the transcript
      into a user message (rather than re-injecting the parent's typed
      messages into the sub-agent's history) sidesteps a stack of
      cross-driver pitfalls: Claude rejects consecutive same-role
      messages; the Anthropic SDK silently drops ``role="system"`` from
      its ``messages=`` parameter; rendering structured tool_call /
      tool_result pairs back through a different driver's message-format
      is fragile. A single user message of plain text renders cleanly on
      every driver.

    The sub-agent must call :class:`_SubmitTool` once and exit. Does not
    mutate *history*; raises ``RuntimeError`` if the sub-agent finishes
    without submitting.
    """
    sub_config = dataclasses.replace(
      self.agent_config,
      max_completion_tokens=8192,  # Compaction is a heavy lift; give it a big budget
      enable_memory_compaction=False,
      debug_mode=self.agent_config.debug_mode,
    )
    captured: list = []
    sub_agent = sub_config.create_agent(
      tools=[(_SubmitTool(captured), 1)],
    )

    transcript = self._render_transcript(history)
    sub_agent.append_system_message(self.SYSTEM_PROMPT)
    sub_agent.append_user_message(
      f"=== Conversation log ===\n\n{transcript}\n\n"
      f"=== Instruction ===\n\n{self._INSTRUCTION_MESSAGE}"
    )

    sub_agent.run(
      AgentHooks(
        # The sub-agent must speak via ``submit``. If it chats instead,
        # nudge it back to the tool and keep going — the sub-agent's
        # round/token budget caps how long it can drift before
        # :class:`ReachRoundLimit` / :class:`ReachTokenLimit` bubble out.
        post_response=lambda _: (True, self._CHAT_RETRY_NUDGE),
        # Stop as soon as ``submit`` populates ``captured``. Any other
        # tool call (none registered, but defensive) keeps going.
        post_tool_call=(
          lambda _, __, result: (False, result) if captured else (True, result)
        ),
      )
    )

    # Defensive: ``run()`` only returns via the post_tool_call branch, which
    # only fires after ``submit`` populates ``captured``. If we're here with
    # nothing captured, the run loop returned via a path we don't model
    # (driver bug) — fail loud rather than return an empty summary.
    if not captured:
      raise RuntimeError("Memory compaction sub-agent exited without calling submit")
    return captured[0]

  # -------------------------------------------------------------------
  # Helpers
  # -------------------------------------------------------------------

  @staticmethod
  def _render_transcript(messages: List[ChatMessage]) -> str:
    """Render history messages as a plain-text transcript for the
    summarizer LLM. Tool calls and results are tagged with their call_id
    so the model can pair them visually."""
    parts = []
    for m in messages:
      if isinstance(m, ChatMessageMessage):
        parts.append(f"[{m.role}] {m.content}")
      elif isinstance(m, ChatMessageFunctionCall):
        parts.append(f"[tool_call id={m.call_id}] {m.name}({m.arguments})")
      elif isinstance(m, ChatMessageFunctionCallOutput):
        parts.append(f"[tool_result id={m.call_id}] {m.output}")
    return "\n\n".join(parts)
