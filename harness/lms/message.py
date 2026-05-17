from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal, Union


@dataclass
class ChatMessage:
  type: Union[
    Literal["message"], Literal["function_call"], Literal["function_call_output"]
  ]

  @abstractmethod
  def is_from_user(self) -> bool:
    """True for messages issued by the user."""
    ...


@dataclass
class ChatMessageMessage(ChatMessage):
  role: str = Union[Literal["system"], Literal["user"], Literal["assistant"]]
  content: str = ""
  type: str = "message"

  def is_from_user(self) -> bool:
    return self.role != "assistant"


@dataclass
class ChatMessageFunctionCall(ChatMessage):
  call_id: str = ""
  name: str = ""
  arguments: str = ""
  type: str = "function_call"

  def is_from_user(self) -> bool:
    return False


@dataclass
class ChatMessageFunctionCallOutput(ChatMessage):
  call_id: str = ""
  output: str = ""
  type: str = "function_call_output"

  def is_from_user(self) -> bool:
    return True
