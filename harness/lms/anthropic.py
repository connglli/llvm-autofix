import json
import os

from anthropic import Anthropic, omit
from typing_extensions import deprecated

from harness.lms.agent import AgentBase, AgentConfig, AgentHooks
from harness.lms.message import (
  ChatMessageFunctionCall,
  ChatMessageMessage,
)
from harness.lms.meter import GlobalMeter


@deprecated("Use ClaudeGenericAgent instead")
class ClaudeAgent(AgentBase):
  def __init__(self, config: AgentConfig):
    super().__init__(config)
    if self.reasoning_effort == "NOT_GIVEN":
      self.reasoning_effort = omit
      self.thinking = omit
    elif self.reasoning_effort == "none":
      self.thinking = "disabled"
    else:
      self.thinking = "adaptive"
    self.console.print(
      "WARNING: Temperature setting has been deprecated for Claude models and will be ignored."
    )
    self.console.print(
      "WARNING: Top-p setting has been deprecated for Claude models and will be ignored."
    )
    api_key = os.environ.get("LLVM_HARNESS_LM_API_KEY")
    base_url = os.environ.get("LLVM_HARNESS_LM_API_ENDPOINT") or None
    self.client = Anthropic(api_key=api_key, base_url=base_url)

  def render_message_list(self) -> list[dict]:
    """Serialize :attr:`history` into Claude's strict-alternation message
    format. A ``ChatMessageFunctionCall`` folds into the immediately
    preceding assistant message (so text + tool_use ship as one turn);
    otherwise it stands alone (post-compaction tail).
    """
    messages = []
    if self.tools.has_deferred_tools():
      messages.append(
        {
          "role": "user",
          "content": "NOTE: "
          'Some of the provided tools may be marked by "[deferred]" in their description. '
          "This means their descriptions and specifications are not fully provided. "
          "Therefore, for these tools, be sure to use `tool_search` to load the full "
          "description and specification before calling them.",
        }
      )

    for msg in self.history:
      if isinstance(msg, ChatMessageMessage) and msg.role != "assistant":
        # user (and system, which our framework degrades to user historically)
        role = "user" if msg.role == "system" else msg.role
        messages.append({"role": role, "content": msg.content})
      elif isinstance(msg, ChatMessageMessage):  # role == "assistant"
        if msg.content:  # Claude rejects empty text blocks
          messages.append(
            {"role": "assistant", "content": [{"type": "text", "text": msg.content}]}
          )
      elif isinstance(msg, ChatMessageFunctionCall):
        block = {
          "type": "tool_use",
          "id": msg.call_id,
          "name": msg.name,
          "input": json.loads(msg.arguments) if msg.arguments else {},
        }
        if messages and messages[-1]["role"] == "assistant":
          messages[-1]["content"].append(block)
        else:
          messages.append({"role": "assistant", "content": [block]})
      else:  # ChatMessageFunctionCallOutput
        messages.append(
          {
            "role": "user",
            "content": [
              {
                "type": "tool_result",
                "tool_use_id": msg.call_id,
                "content": msg.output,
              },
            ],
          }
        )
    return messages

  def run(self, hooks: AgentHooks) -> str:
    messages = self.render_message_list()
    while True:
      self.console.print(GlobalMeter.format_status(self.meter))
      self.console.print(self.format_context_window_status())
      self.meter.record_round()

      if self.maybe_compact_history():
        messages = self.render_message_list()

      remaining_tools = self._get_remaining_tools()
      response = self._completion_api_with_backoff(
        model=self.model,
        messages=messages,
        max_tokens=self.max_completion_tokens,
        thinking=self.thinking,
        tools=(
          [tool.spec().render_in_claude_format() for tool in remaining_tools] or omit
        ),
        tool_choice={
          "type": "auto",
          "disable_parallel_tool_use": True,
        },
      )

      # Update tokens that we have consumed
      cached_tokens = (response.usage.cache_read_input_tokens or 0) + (
        response.usage.cache_creation_input_tokens or 0
      )
      input_tokens = response.usage.input_tokens + cached_tokens
      self.record_usage(
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=response.usage.output_tokens,
      )
      messages.append({"role": "assistant", "content": response.content})

      if response.stop_reason == "tool_use":
        for content in response.content:
          if content.type == "text":
            self.append_assistant_message(content.text)
          elif content.type == "tool_use":
            name = content.name
            call_id = content.id
            args = content.input
            args_text = json.dumps(args)
            self.append_function_tool_call(
              call_id=call_id,
              name=name,
              arguments=args_text,
            )
            if hooks.pre_tool_call:
              proceed, pre_result = hooks.pre_tool_call(name, args)
              if not proceed:
                skip_result = str(pre_result)
                self.append_function_tool_call_output(
                  call_id=call_id, result=skip_result
                )
                messages.append(
                  {
                    "role": "user",
                    "content": [
                      {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": skip_result,
                      }
                    ],
                  }
                )
                continue
              if isinstance(pre_result, dict):
                args = pre_result
            result = self.perform_tool_call(name, args)
            proceed, result = hooks.post_tool_call(name, args_text, result)
            if not proceed:
              self.append_user_message(result)
              return result
            self.append_function_tool_call_output(call_id=call_id, result=result)
            messages.append(
              {
                "role": "user",
                "content": [
                  {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": result,
                  }
                ],
              }
            )
      elif response.stop_reason == "stop_sequence":
        text = response.content[0].text
        self.append_assistant_message(text)
        proceed, content = hooks.post_response(text)
        self.append_user_message(content)
        messages.append(
          {
            "role": "user",
            "content": content,
          }
        )
        if not proceed:
          return content

  def _completion_api(self, **kwargs):
    return self.client.messages.create(**kwargs)
