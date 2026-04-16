"""Debug console abstraction with Rich-powered boxed output.

Provides three interchangeable backends behind a common interface:

* **MockConsole** — silent no-op (used when debug mode is off).
* **BoxedConsole** — Rich panels printed to the terminal.
* **FileConsole** — plain-text output appended to a log file.

Use :func:`get_boxed_console` to obtain the right backend based on the
current :class:`BoxedConsoleConfigs` settings.
"""

import threading
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel


@dataclass
class BoxedConsoleConfigs:
  """Global configuration knobs for the console system.

  Set these class-level attributes before creating any consoles.
  """

  box_width: Optional[int] = None  # Terminal column width for Rich panels
  out_dir: Optional[str] = None  # If set, log to files instead of terminal
  print_to_console: bool = False  # Also echo to stdout when logging to files


class BoxedConsoleBase:
  """Abstract base for all console backends."""

  @abstractmethod
  def printb(self, *args, **kwargs): ...

  @abstractmethod
  def print(self, *args, **kwargs): ...

  @classmethod
  def _make_box_title(cls, title):
    """Append the current thread identifier to a panel title."""
    return f"{title} [{cls._thread_id()}]"

  @staticmethod
  def _thread_id():
    curr_thr = threading.current_thread()
    return f"{curr_thr.name}@{curr_thr.native_id}"


class MockConsole(BoxedConsoleBase):
  """Silent console — all output is discarded."""

  def printb(self, *args, **kwargs):
    pass

  def print(self, *args, **kwargs):
    pass


class FileConsole(BoxedConsoleBase):
  """Append-only plain-text console backed by a log file."""

  def __init__(
    self, *, out_file: str, title: Optional[str], print_to_console: bool = False
  ):
    self.title = title
    self.out_file = out_file
    self.print_to_console = print_to_console

  def printb(self, *, message, title=None, **kwargs):
    """Write a titled block to the log file."""
    title = self._make_box_title(title or self.title)
    long_msg = ""
    if title:
      long_msg += f"--- {title} --------\n"
    long_msg += message
    long_msg += "\n"
    with open(self.out_file, "a") as fou:
      fou.write(long_msg)
    if self.print_to_console:
      print(long_msg)

  def print(self, message, **kwargs):
    long_msg = message + "\n"
    with open(self.out_file, "a") as fou:
      fou.write(long_msg)
    if self.print_to_console:
      print(long_msg)


class BoxedConsole(BoxedConsoleBase):
  """Rich-powered terminal console that renders messages inside panels."""

  def __init__(self, *, box_width, box_title, box_bg_color="black"):
    # FIX: disable markup (i.e., [...] styles) since our messages may contain [...]
    self.console = Console(markup=False)
    self.box_width = box_width
    self.box_title = box_title
    self.box_bg_color = box_bg_color

  def printb(self, *, message, title=None, background=None):
    """Print *message* inside a Rich panel with an optional *title*."""
    title = self._make_box_title(title or self.box_title)
    background = background or self.box_bg_color
    self.console.print(
      Panel(
        f"{message}",
        title=title,
        title_align="left",
        width=self.box_width,
        style=f"on {background}",
      )
    )

  def print(self, message, color=None):
    style = f"{color} on {self.box_bg_color}" if color else f"on {self.box_bg_color}"
    self.console.print(message, width=self.box_width, style=style)


def get_boxed_console(
  box_title=None, box_bg_color="black", console_name="harness", debug_mode=False
) -> BoxedConsoleBase:
  """Factory — returns the appropriate console backend.

  When *debug_mode* is False, returns a :class:`MockConsole` (silent).
  Otherwise, returns a :class:`FileConsole` or :class:`BoxedConsole`
  depending on whether :attr:`BoxedConsoleConfigs.out_dir` is set.
  """
  if debug_mode:
    if BoxedConsoleConfigs.out_dir:
      return FileConsole(
        out_file=str(
          (Path(BoxedConsoleConfigs.out_dir) / (console_name + ".traj.log")).resolve()
        ),
        title=box_title,
        print_to_console=BoxedConsoleConfigs.print_to_console,
      )
    else:
      return BoxedConsole(
        box_width=BoxedConsoleConfigs.box_width,
        box_title=box_title,
        box_bg_color=box_bg_color,
      )
  else:
    return MockConsole()
