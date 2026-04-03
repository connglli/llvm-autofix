from harness.llvm.access import AccessControl
from harness.llvm.harness import Harness, Reproducer

__all__ = [
  "AccessControl",
  "CodeLine",
  "CodeSnippet",
  "FixEnv",
  "Harness",
  "Reproducer",
]


def __getattr__(name: str):
  if name == "FixEnv":
    from harness.llvm.intern.lab_env import FixEnv

    return FixEnv
  if name == "CodeLine":
    from harness.llvm.intern.llvm_code import CodeLine

    return CodeLine
  if name == "CodeSnippet":
    from harness.llvm.intern.llvm_code import CodeSnippet

    return CodeSnippet
  raise AttributeError(f"module 'harness.llvm' has no attribute {name!r}")
