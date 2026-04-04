import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

import tree_sitter_cpp
from tree_sitter import Language, Parser, Tree, TreeCursor

from harness.llvm.intern.llvm import llvm_dir


@dataclass
class CodeLine:
  line_number: int
  code: str
  annotation: str = ""


class CodeSnippet:
  header: str
  lines: Dict[int, CodeLine]

  def __init__(self):
    self.header = ""
    self.lines = dict()

  def add_line(self, line: CodeLine):
    line.code = line.code.rstrip("\n")
    self.lines[line.line_number] = line

  def add_annotation(self, line_number: int, annotation: str):
    if line_number in self.lines:
      self.lines[line_number].annotation = annotation
    else:
      self.lines[line_number] = CodeLine(line_number, "", annotation)

  def set_header(self, header: str):
    self.header = header

  def render(self) -> str:
    rendered = self.header
    if len(self.lines) == 0:
      return rendered

    left_width = len(str(max(self.lines.keys()))) + 1
    line_count = 0
    for line_number in sorted(self.lines.keys()):
      line = self.lines[line_number]
      rendered += f"{line_number:<{left_width}}{line.code}"
      if line.annotation:
        rendered += f"// {line.annotation}"
      rendered += "\n"
      line_count += 1
      if line_count >= 250:
        rendered += "// ... (truncated)\n"
        break

    return rendered


class LlvmCode:
  def __init__(self):
    self.llvm_dir = Path(llvm_dir)
    CXX_LANGUAGE = Language(tree_sitter_cpp.language())
    self.cxx_parser = Parser(CXX_LANGUAGE)

  _USEFUL_ANALYSIS_PASSES = {
    "print<scalar-evolution>": [
      "constraint-elimination",
      "irce",
      "indvars",
      "licm",
      "loop-delete",
      "loop-distribute",
      "loop-flatten",
      "loop-fusion",
      "loop-idiom",
      "loop-interchange",
      "loop-load-elim",
      "loop-predication",
      "loop-rotate",
      "loop-simplifycfg",
      "loopsink",
      "loop-reduce",
      "loop-term-fold",
      "loop-unroll-and-jam",
      "loop-unroll",
      "loop-versioning-licm",
      "nary-reassociate",
      "simple-loop-unswitch",
      "canon-freeze",
      "lcssa",
      "loop-constrainer",
      "loop-peel",
      "loop-simplify",
      "load-store-vectorizer",
      "loop-vectorize",
      "slp-vectorizer",
    ],
    "aa-eval": [
      "aggressive-instcombine",
      "coro-elide",
      "instcombine",
      "inline",
      "dse",
      "flatten-cfg",
      "gvn",
      "gvn-hoist",
      "jump-threading",
      "licm",
      "loop-idiom",
      "loop-predication",
      "loop-versioning",
      "memcpyopt",
      "mergeicmps",
      "newgvn",
      "tailcallelim",
      "load-store-vectorizer",
    ],
  }

  def resolve_pass_name(self, args: str) -> Tuple[str, List[str]]:
    """Resolve the pass name(s) of the given llvm file"""
    # TODO: Support more closely-bound analysis passes
    pos = args.find("passes=")
    next = args.find(" ", pos)
    pass_name = args[pos + 7 : next]

    analysis_passes = []

    for name, keys in self._USEFUL_ANALYSIS_PASSES.items():
      for key in keys:
        if key in pass_name:
          analysis_passes.append(name)
          break

    return pass_name, analysis_passes

  def resolve_pass_opts(self, pass_name: str) -> List[str]:
    """Resolve the useful options of a given pass"""
    if pass_name == "aa-eval":
      return ["-aa-pipeline=basic-aa", "-print-all-alias-modref-info"]
    return []

  def resolve_debug_types(self, files: Set[Path]) -> List[str]:
    """Resolve debug types of given files"""
    # FIXME: This is not always safe, an edge case: https://github.com/llvm/llvm-project/blob/4f8597f071bab5113a945bd653bec84bd820d4a3/llvm/lib/Transforms/Scalar/LoopLoadElimination.cpp#L64-L65
    pattern = re.compile(r'#define DEBUG_TYPE "(.+)"')
    debug_types = set()
    for file in files:
      if file.match("llvm/lib/Analysis/*.cpp") or file.match(
        "llvm/lib/Transforms/*/*.cpp"
      ):
        content = (self.llvm_dir / file).read_text()
        match = pattern.search(content)
        if match:
          debug_type = match.group(1)
          debug_types.add(debug_type.strip())
    return list(debug_types)

  def find_function(
    self, tree: Tree, start_line: int, end_line: int, func_name: str
  ) -> TreeCursor:
    cursor = tree.walk()

    reached_root = False
    while not reached_root:
      # Extra one line for return type which is not in the same line as the function name
      if (
        cursor.node.type == "function_definition"
        and cursor.node.start_point.row + 1 + 1 >= start_line
        and cursor.node.end_point.row + 1 <= end_line
      ):
        func_name_node = cursor.node.children_by_field_name("declarator")[0]
        while True:
          decl = func_name_node.children_by_field_name("declarator")
          if len(decl) == 0:
            if func_name_node.type == "reference_declarator":
              func_name_node = func_name_node.child(1)
              continue
            break
          func_name_node = decl[0]
        cur_func_name = func_name_node.text.decode("utf-8")
        if func_name in cur_func_name:
          return cursor

      if cursor.goto_first_child():
        continue

      if cursor.goto_next_sibling():
        continue

      retracing = True
      while retracing:
        if not cursor.goto_parent():
          retracing = False
          reached_root = True

        if cursor.goto_next_sibling():
          retracing = False

    return None

  def get_full_func_def(
    self, code: CodeSnippet, lines: List[str], start_line: int, end_line: int
  ) -> CodeSnippet:
    for line in range(start_line, end_line + 1):
      code.add_line(CodeLine(line, lines[line]))
    return code

  def collect_header_comments(self, lines: List[str], start_lineno: int) -> str:
    header_comments = ""
    for i in range(start_lineno - 1, 0, -1):
      line = lines[i].lstrip()
      if line.startswith("//"):
        header_comments = line + header_comments
      elif i != start_lineno - 1:
        # Extra one line for return type which is not in the same line as the function name
        break
    return header_comments

  def get_func_stem(self, func_name: str) -> str:
    if "(" in func_name:
      func_name = func_name[: func_name.index("(")]

    if "::" in func_name:
      func_name = func_name[func_name.rindex("::") + 2 :]

    return func_name

  def render_func_code(
    self, func_name: str, start_line: int, file_name: str
  ) -> CodeSnippet:
    code = CodeSnippet()

    # Accept both absolute paths and paths relative to llvm_dir.
    file_path = Path(file_name)
    if not file_path.is_absolute():
      file_path = self.llvm_dir / file_path

    with open(file_path, "r") as f:
      src = f.read()
    lines = [""] + src.splitlines(keepends=True)
    if start_line >= len(lines):
      code.set_header("Unavailable")
      return code

    tree = self.cxx_parser.parse(bytes(src, "utf8"))
    cursor = self.find_function(
      tree, start_line, int(1e10), self.get_func_stem(func_name)
    )
    if not cursor:
      code.set_header("Unavailable")
      return code
    header_comments = self.collect_header_comments(lines, start_line)
    code.set_header(header_comments)
    start_line = min(cursor.node.start_point.row + 1, start_line)
    end_line = cursor.node.end_point.row
    return self.get_full_func_def(code, lines, start_line, end_line + 1)

  def extract_snippet(
    self,
    file: str,
    start_line: int,
    end_line: int,
    *,
    context: int = 0,
  ) -> str:
    """Read source lines from *file* and render as a :class:`CodeSnippet`.

    Lines are 1-indexed.  *context* adds extra lines before and after
    the specified range.
    """
    file_path = Path(file) if Path(file).is_absolute() else self.llvm_dir / file
    if not file_path.exists():
      raise ValueError(f"File {file} does not exist.")
    lines = [""] + file_path.read_text().splitlines()
    if start_line < 1 or end_line < 1:
      raise ValueError(
        f"Line numbers {start_line} and {end_line} must be positive integers."
      )
    if start_line > end_line:
      raise ValueError(
        f"Start line {start_line} cannot be greater than end line {end_line}."
      )
    if max(start_line, end_line) >= len(lines):
      raise ValueError(
        f"Line numbers {start_line} and {end_line} are out of bounds for {file}"
      )
    start_line = max(1, start_line - context)
    end_line = min(len(lines) - 1, end_line + context)
    code = CodeSnippet()
    for line in range(start_line, end_line + 1):
      code.add_line(CodeLine(line, lines[line].rstrip()))
    return code.render()

  def parse_langref_desc(self, keywords: set[str]) -> dict[str, str]:
    """Extract LangRef documentation for the given IR keywords."""
    langref_path = self.llvm_dir / "llvm" / "docs" / "LangRef.rst"
    if not langref_path.exists():
      return {}
    langref = langref_path.read_text()
    desc = {}
    sep1 = ".. _"
    sep2 = "\n^^^"
    for keyword in keywords:
      matched = re.search(f"\n'``{keyword}.+\n\\^", langref)
      if matched is None:
        continue
      beg, end = matched.span()
      beg = langref.rfind(sep1, None, beg)
      end1 = langref.find(sep2, end)
      end2 = langref.rfind(sep1, None, end1)
      desc[keyword] = langref[beg:end2]
    return desc

  @staticmethod
  def infer_related_components(diff_files: list[str]) -> set[str]:
    """Map changed file paths to LLVM component names."""
    prefixes = [
      "llvm/lib/Analysis/",
      "llvm/lib/Transforms/Scalar/",
      "llvm/lib/Transforms/Vectorize/",
      "llvm/lib/Transforms/Utils/",
      "llvm/lib/Transforms/IPO/",
      "llvm/lib/Transforms/",
      "llvm/lib/IR/",
    ]
    components = set()
    for file in diff_files:
      for prefix in prefixes:
        if file.startswith(prefix):
          component_name = (
            file.removeprefix(prefix)
            .split("/")[0]
            .removesuffix(".cpp")
            .removesuffix(".h")
          )
          if component_name != "":
            if (
              component_name.startswith("VPlan")
              or component_name.startswith("LoopVectoriz")
              or component_name.startswith("VPRecipe")
            ):
              component_name = "LoopVectorize"
            if component_name.startswith("ScalarEvolution"):
              component_name = "ScalarEvolution"
            if component_name.startswith("ConstantFold"):
              component_name = "ConstantFold"
            if "AliasAnalysis" in component_name:
              component_name = "AliasAnalysis"
            if component_name.startswith("Attributor"):
              component_name = "Attributor"
            if file.startswith("llvm/lib/IR"):
              component_name = "IR"
            components.add(component_name)
            break
    return components

  @staticmethod
  def parse_ir_keywords(ir: str) -> set[str]:
    """Extract instruction and intrinsic names from LLVM IR text."""
    keywords = set()
    instruction_pattern = re.compile(r"%.+ = (\w+) ")
    for match in re.findall(instruction_pattern, ir):
      keywords.add(match)
    intrinsic_pattern = re.compile(r"@(llvm.\w+)\(")
    for match in re.findall(intrinsic_pattern, ir):
      keywords.add(match)
    keywords.discard("call")
    return keywords
