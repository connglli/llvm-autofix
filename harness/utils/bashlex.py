"""Extract command names from Bash snippets using tree-sitter.

Uses the tree-sitter Bash grammar to parse shell code and collect every
``command_name`` node.  This is used to identify which executables a shell
script invokes without actually running it.
"""

import tree_sitter_bash
from tree_sitter import Language, Parser

BASH_LANGUAGE = Language(tree_sitter_bash.language())
bash_parser = Parser(BASH_LANGUAGE)


def get_commands(code: str) -> list[str]:
  """Return a list of command names found in a Bash code snippet.

  Example::

      >>> get_commands("echo hello && ls -la | grep foo")
      ['echo', 'ls', 'grep']
  """
  tree = bash_parser.parse(code.encode())
  cmds = []

  def _visit(node, depth):
    if node.type == "command_name":
      cmds.append(code[node.start_byte : node.end_byte].strip().split("\\n")[0])
    for child in node.children:
      _visit(child, depth + 1)

  _visit(tree.root_node, 0)

  return cmds
