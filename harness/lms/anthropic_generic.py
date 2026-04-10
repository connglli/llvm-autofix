import os
from typing import Dict, List, Tuple

from anthropic import Anthropic, omit

from harness.lms.agent import AgentConfig
from harness.lms.generic import GenericAgent


class ClaudeGenericAgent(GenericAgent):
  def __init__(self, config: AgentConfig):
    super().__init__(config)
    if self.reasoning_effort == "NOT_GIVEN":
      self.reasoning_effort = omit
      self.thinking = omit
    elif self.reasoning_effort == "none":
      self.thinking = "disabled"
    else:
      self.thinking = "adaptive"
    api_key = os.environ.get("LLVM_HARNESS_LM_API_KEY")
    base_url = os.environ.get("LLVM_HARNESS_LM_API_ENDPOINT") or None
    self.client = Anthropic(api_key=api_key, base_url=base_url)

  def _complete_chat(self, messages: List[Dict]) -> Tuple[str, str]:
    response = self._completion_api_with_backoff(
      model=self.model,
      messages=messages,
      temperature=self.temperature,
      max_tokens=self.max_completion_tokens,
      thinking=self.thinking,
      stream=False,
    )

    # Update tokens that we have consumed
    self.meter.record_usage(
      input_tokens=response.usage.input_tokens,
      cached_tokens=response.usage.cache_read_input_tokens,
      output_tokens=response.usage.output_tokens,
    )

    # Get assistant's reasoning and answer from the response content
    reasoning_content = []
    answer_content = []

    for content in response.content:
      if content.type == "thinking":
        reasoning_content.append(content.thinking)
      elif content.type == "text":
        answer_content.append(content.text)

    return "\n".join(reasoning_content), "\n".join(answer_content)

  def _completion_api(self, **kwargs):
    return self.client.messages.create(**kwargs)
