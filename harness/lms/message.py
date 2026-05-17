from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union


@dataclass
class ChatMessage:
  type: Union[
    Literal["message"], Literal["function_call"], Literal["function_call_output"]
  ]


@dataclass
class ChatMessageMessage(ChatMessage):
  role: str = Union[Literal["system"], Literal["user"], Literal["assistant"]]
  content: str = ""
  type: str = "message"


@dataclass
class ChatMessageFunctionCall(ChatMessage):
  call_id: str = ""
  name: str = ""
  arguments: str = ""
  type: str = "function_call"


@dataclass
class ChatMessageFunctionCallOutput(ChatMessage):
  call_id: str = ""
  output: str = ""
  type: str = "function_call_output"
