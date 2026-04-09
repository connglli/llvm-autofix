"""Issue description types for the LLVM harness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Reproducer:
  """Reproducer specification — file, commands, and test bodies."""

  file: str
  commands: list[str]
  tests: list[dict]  # [{test_name, test_body, additional_args?}]


@dataclass
class IssueCard:
  """Describes an LLVM issue.  Defaults align with open issues against trunk.

  Construct directly::

      IssueCard(
          bug_type="crash",
          reproducers=[Reproducer(
              file="test.ll",
              commands=["opt -O2 < %s"],
              tests=[{"test_name": "<module>", "test_body": "..."}],
          )],
      )
  """

  # Required
  bug_type: str  # "crash" | "miscompilation" | "hang"
  reproducers: list[Reproducer]

  # Optional (defaults for open issues)
  base_commit: str | None = None  # None → HEAD
  test_commit: str | None = None  # None → same as base_commit
  lit_test_dir: list[str] | None = None

  # Optional (context)
  issue: dict | None = None  # {title, body, author, labels, comments}
