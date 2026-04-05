import threading
from dataclasses import dataclass
from typing import Optional


class ReachRoundLimit(StopIteration):
  def __init__(self):
    super().__init__("Reached the round limit for agent execution.")


class ReachTokenLimit(StopIteration):
  def __init__(self):
    super().__init__("Reached the token limit for agent execution.")


@dataclass
class AgentMeter:
  """Tracks token/round consumption for a single agent.

  Does not enforce limits — enforcement is handled by the GlobalMeter.
  """

  chat_rounds: int = 0
  input_tokens: int = 0
  cached_tokens: int = 0
  output_tokens: int = 0
  total_tokens: int = 0

  def record_round(self):
    self.chat_rounds += 1
    GlobalMeter.instance().check()

  def record_usage(
    self,
    input_tokens: int = 0,
    cached_tokens: int = 0,
    output_tokens: int = 0,
  ):
    self.input_tokens += input_tokens
    self.cached_tokens += cached_tokens
    self.output_tokens += output_tokens
    self.total_tokens += input_tokens + output_tokens
    GlobalMeter.instance().check()


class GlobalMeter:
  """Singleton that aggregates all agent meters and enforces global limits.

  Usage::

      # At startup, configure the global limits
      GlobalMeter.configure(token_limit=5_000_000, round_limit=500)

      # Each agent gets its own AgentMeter, registered with the global meter
      meter = GlobalMeter.instance().create_meter()

      # Inside agent loops
      meter.record_round()
      meter.record_usage(input_tokens=..., output_tokens=...)
      # ^^ these automatically call GlobalMeter.check() which raises
      #    ReachTokenLimit / ReachRoundLimit when the global budget is exceeded.
  """

  _instance: "GlobalMeter | None" = None
  _lock: threading.Lock = threading.Lock()

  def __init__(
    self,
    *,
    token_limit: Optional[int] = None,
    round_limit: Optional[int] = None,
  ):
    self.token_limit = token_limit
    self.round_limit = round_limit
    self._meters: list[AgentMeter] = []

  @classmethod
  def configure(
    cls,
    *,
    token_limit: Optional[int] = None,
    round_limit: Optional[int] = None,
  ) -> "GlobalMeter":
    """Create (or reconfigure) the singleton GlobalMeter."""
    with cls._lock:
      if cls._instance is None:
        cls._instance = cls(token_limit=token_limit, round_limit=round_limit)
      else:
        cls._instance.token_limit = token_limit
        cls._instance.round_limit = round_limit
      return cls._instance

  @classmethod
  def instance(cls) -> "GlobalMeter":
    """Return the singleton, creating a no-limit instance if needed."""
    if cls._instance is None:
      with cls._lock:
        if cls._instance is None:
          cls._instance = cls()
    return cls._instance

  @classmethod
  def reset(cls):
    """Reset the singleton. Primarily for testing."""
    with cls._lock:
      cls._instance = None

  def create_meter(self) -> AgentMeter:
    """Create a new AgentMeter and register it for global tracking."""
    meter = AgentMeter()
    self._meters.append(meter)
    return meter

  @property
  def total_tokens(self) -> int:
    return sum(m.total_tokens for m in self._meters)

  @property
  def total_rounds(self) -> int:
    return sum(m.chat_rounds for m in self._meters)

  @property
  def total_input_tokens(self) -> int:
    return sum(m.input_tokens for m in self._meters)

  @property
  def total_cached_tokens(self) -> int:
    return sum(m.cached_tokens for m in self._meters)

  @property
  def total_output_tokens(self) -> int:
    return sum(m.output_tokens for m in self._meters)

  def check(self):
    """Raise if any global limit is exceeded."""
    if self.round_limit is not None and self.total_rounds > self.round_limit:
      raise ReachRoundLimit()
    if self.token_limit is not None and self.total_tokens >= self.token_limit:
      raise ReachTokenLimit()

  def stats(self) -> dict:
    """Return aggregated statistics across all meters."""
    return {
      "chat_rounds": self.total_rounds,
      "input_tokens": self.total_input_tokens,
      "cached_tokens": self.total_cached_tokens,
      "output_tokens": self.total_output_tokens,
      "total_tokens": self.total_tokens,
    }

  @staticmethod
  def format_status(agent_meter: AgentMeter) -> str:
    """Format a status line showing both agent and global meter stats."""
    m = agent_meter
    gs = GlobalMeter.instance().stats()
    return (
      f"Executing round #{m.chat_rounds} | "
      f"current.input_tokens={m.input_tokens}, current.cached_tokens={m.cached_tokens}, "
      f"current.output_tokens={m.output_tokens}, current.total_tokens={m.total_tokens} | "
      f"global.rounds={gs['chat_rounds']}, global.input_tokens={gs['input_tokens']}, "
      f"global.cached_tokens={gs['cached_tokens']}, global.output_tokens={gs['output_tokens']}, "
      f"global.total_tokens={gs['total_tokens']}"
    )
