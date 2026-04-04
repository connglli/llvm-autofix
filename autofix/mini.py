import json
import os
import time
from argparse import ArgumentParser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

import harness
from harness.llvm import (
  AccessControl,
  Harness,
  Reproducer,
)
from harness.llvm.debugger import DebuggerBase, StackTrace
from harness.lms.agent import AgentBase
from harness.lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from harness.utils.console import get_boxed_console

# - ===============================================
# - Prompts
# - ===============================================

_PROMPTS = harness.load_yaml_config("autofix", "mini.yaml")["prompts"]
PROMPT_REASON = _PROMPTS["reason"]
PROMPT_REPAIR = _PROMPTS["repair"]

# - ===============================================
# - Agent configurations
# - ===============================================

# We restrict the agent to chat at most 500 rounds for each run
# and consume at most 5 million tokens among all runs.
AGENT_TEMPERATURE = 0
AGENT_TOP_P = 0.95
AGENT_MAX_COMPLETION_TOKENS = 8092
AGENT_REASONINT_EFFORT = "NOT_GIVEN"
AGENT_MAX_CHAT_ROUNDS = 500
AGENT_MAX_CONSUMED_TOKENS = 5_000_000
# We give context gathering tools more budget and restrict the models
# to be careful and think twice when they are editing and testing.
MAX_TCS_GET_CONTEXT = 250
MAX_TCS_EDIT_AND_TEST = 25
MIN_EDIT_POINT_LINES = 1
# Enabled tools and their categories
# Note these list should also include skills (a special type of tools).
ENABLED_REASON_TOOLS = {
  # Explore codebase tools
  "list",
  "read",
  "find",
  "ripgrep",
  "code",
  # Documentation tools
  "docs",
  "langref",
  # Debugging tools
  "debug",
  "eval",
  # Report tool to finish the analysis
  "report",
}
ENABLED_REPAIR_TOOLS = {
  # Explore codebase tools
  "list",
  "read",
  "find",
  "ripgrep",
  "code",
  "bash",
  "write",
  # Documentation tools
  "docs",
  "langref",
  # Edit tools
  "edit",
  # Test tools
  "reset",
  "test",
  "preview",
  "interpret_ir",
  "optimize_ir",
  "verify_ir",
  "compile_ir",
  # Patch review skill
  "llvm-patchreview",
}
ENABLED_TOOLS = ENABLED_REASON_TOOLS | ENABLED_REPAIR_TOOLS
EDIT_AND_TEST_TOOLS = {"edit", "reset", "test"}
GET_CONTEXT_TOOLS = ENABLED_TOOLS - EDIT_AND_TEST_TOOLS
# Enabled skills: only list skills
ENABLED_SKILLS = {"llvm-patchreview"}

# - ================================================
# - LLVM settings
# - ================================================

ASSERTION_FUNCTION_LIST = [
  "__assert_fail",
  "__GI___assert_fail",
  "llvm::llvm_unreachable_internal",
  "llvm::report_fatal_error",
]

# NOTE: Patterns start with star will be passed into rbreak.
# FIXME: rbreak is slow. Use grep instead?
TRANSFORMATION_FUNCTION_LIST = [
  "Instruction::clone",
  "Instruction::replaceSuccessorWith",
  "Instruction::setSuccessor",
  "User::setOperand",
  "::eraseFromParent",
  "Use::set",
  "Use::operator=",
  "User::replaceUsesOfWith",
  "Value::replaceAllUsesWith",
  "InstCombiner::InsertNewInstBefore",
  "InstCombiner::InsertNewInstWith",
  "InstCombiner::replaceInstUsesWith",
  "InstCombiner::replaceOperand",
  "InstCombiner::replaceUse",
  "SwitchInst::addCase",
  "SwitchInst::removeCase",
  "BinaryOperator::swapOperands",
  "BranchInst::swapSuccessors",
  "BranchInst::setCondition",
  "BranchInst::setSuccessor",
  "SwitchInst::setCondition",
  "SwitchInst::setDefaultDest",
  "SwitchInst::setSuccessor",
  "CmpInst::swapOperands",
  "ICmpInst::swapOperands",
  "FCmpInst::swapOperands",
  "CmpInst::setPredicate",
  "PHINode::addIncoming",
  "PHINode::setIncomingValue",
  "PHINode::addIncoming",
  "*Inst::Create",
  "*Inst::operator new",
  "*BinaryOperator::Create",
  "*IRBuilderBase::Create",
]

COMPILATION_FLAGS = "-O0 -ggdb"
ADDITIONAL_CMAKE_FLAGS = [
  f"-DCMAKE_C_FLAGS_RELWITHDEBINFO={COMPILATION_FLAGS}",
  f"-DCMAKE_CXX_FLAGS_RELWITHDEBINFO={COMPILATION_FLAGS}",
]

# - ================================================
# - Statistis and output
# - ================================================

console = get_boxed_console(debug_mode=False)


def panic(msg: str):
  console.print(f"Error: {msg}", color="red")
  exit(1)


@dataclass
class RunStats:
  # Command to run autofix
  command: dict
  # The generated path for successful runs
  patch: Optional[str] = None
  # The error message for failed runs
  error: Optional[str] = None
  errmsg: Optional[str] = None
  traceback: Optional[str] = None
  # Agent interaction stats
  input_tokens: int = 0
  output_tokens: int = 0
  cached_tokens: int = 0
  total_tokens: int = 0
  chat_rounds: int = 0
  total_time_sec: float = 0.0
  # Fix stats
  trans_point: Tuple[str, str] = ("<not-provided>", "<not-provided>")
  editpoints: List[Tuple[str, int, int]] = field(
    default_factory=lambda *_, **__: [("<not-provided>", -1, -1)]
  )
  reasoning: str = "<not-provided>"
  test_traj: List[str] = field(
    default_factory=list
  )  # Trajectories of patches ever tried during testing
  rev_traj: List[str] = field(
    default_factory=list
  )  # Trajectories of patches submitted for review
  rep_traj: List[str] = field(
    default_factory=list
  )  # Trajectories of review reports for reviewed patches
  patch_report: Optional[str] = (
    None  # Final patch report (root cause + fix explanation)
  )

  def as_dict(self) -> dict:
    return asdict(self)


# - ===============================================
# - Agent's main code
# - ==============================================


class NoAvailablePatchFound(Exception):
  pass


class ReachToolBudget(Exception):
  pass


@dataclass
class PatchEditPoint:
  """A class to represent an edit point in a patch."""

  start: int
  end: int
  file: Path

  def as_tuple(self) -> Tuple[str, int, int]:
    return (str(self.file), self.start, self.end)

  def __str__(self) -> str:
    return f"{self.file}:{self.start}-{self.end}"


def ensure_tools_available(agent: AgentBase, tools: List[str]):
  available_tools = agent.tools.list(ignore_budget=False)
  unavailable_tools = []
  for tool in tools:
    if tool not in available_tools:
      unavailable_tools.append(tool)
  if len(unavailable_tools) > 0:
    raise ReachToolBudget(f"Tools [{', '.join(unavailable_tools)}] are out of budget.")


EDIT_POINT_FORMAT = """\
```cpp
// {file}:{start}-{end}
{code}
```\
"""


_REVIEW_FORMAT_ERROR = (
  "Error: The review report must be valid Markdown with YAML frontmatter "
  "containing a `verdict` field (APPROVE, REVISE, or REJECT). "
  "Output ONLY the report — no surrounding explanations or ```markdown fences. "
  "Expected format:\n\n"
  "---\n"
  "verdict: APPROVE | REVISE | REJECT\n"
  "---\n\n"
  "# Patch Review Report\n"
  "..."
)


def _parse_review_verdict(report: str) -> Optional[str]:
  """Parse the verdict from a review report's YAML frontmatter.

  Returns the verdict string (APPROVE/REVISE/REJECT) or None if the
  report is not valid Markdown with YAML frontmatter.
  """
  report = report.strip()
  start = report.find("---")
  if start == -1:
    return None  # No frontmatter start found
  end = report.find("---", 3)
  if end == -1:
    return None  # No frontmatter end found

  try:
    header = yaml.safe_load(report[3:end])
    if not isinstance(header, dict):
      return None  # Invalid frontmatter format
    verdict = str(header.get("verdict", "")).strip().upper()
    if verdict in ("APPROVE", "REVISE", "REJECT"):
      return verdict
    return None  # Unknown verdict value
  except Exception:
    return None  # Invalid YAML format


def patch_and_fix(
  edit_points: List[PatchEditPoint],
  reason_info: str,
  *,
  rep: Reproducer,
  agent: AgentBase,
  harness: Harness,
  stats: RunStats,
) -> Optional[str]:
  fixenv = harness.fixenv
  console.print(
    f"Generating patch for edit points: {', '.join([str(ep) for ep in edit_points])} ..."
  )

  # Reset the LLVM repo to the base commit
  harness.git("checkout", ".")
  agent.clear_history()

  # Fix: There're chances that the model proposes incorrect edit points
  formatted_edit_points = []
  for ep in edit_points:
    try:
      formatted_edit_points.append(
        EDIT_POINT_FORMAT.format(
          file=ep.file,
          start=ep.start,
          end=ep.end,
          code=harness.llvmcode.extract_snippet(
            str(ep.file),
            ep.start,
            ep.end,
            context=5,
          ),
        )
      )
    except ValueError as e:
      console.print(
        f"Warning: Skip: Failed to extract code snippet for edit point {ep}: {e}",
        color="yellow",
      )

  # Generate the patch according to the information and proposed edit points
  agent.append_user_message(
    PROMPT_REPAIR.format(
      reprod_code=rep.file_path.read_text(),
      issue_symptom=rep.symptom,
      reason_info=reason_info,
      edit_points="\n".join(formatted_edit_points) or "<not-found>",
    )
  )

  # The model drives the repair-review cycle autonomously:
  # it edits, tests, calls llvm-patchreview, revises if needed, and
  # only submits once the reviewer approves.
  has_review_skill = any(sk.name in ENABLED_SKILLS for sk in harness.get_skills())

  def response_callback(_: str) -> Tuple[bool, str]:
    ensure_tools_available(agent, ["test", "edit"])
    return True, (
      "Error: You are not calling any tool or your tool call format is incorrect. "
      "You should always continue with tool calling and correct tool call format. "
      "Please continue."
      " If you are done, call the `test` tool to see if it passes the tests."
      " If you already called the `test` tool, please check the feedback, adjust the patch, and try again."
    )

  def tool_call_callback(name: str, _: str, res: str) -> Tuple[bool, str]:
    ensure_tools_available(agent, ["test", "edit"])
    if name == "test":
      patch = fixenv.dump_patch()
      stats.test_traj.append(patch)
      if res == "<success>" and not has_review_skill:
        return False, patch  # No review skill — stop on test success
    elif name == "llvm-patchreview":
      patch = fixenv.dump_patch()
      stats.rev_traj.append(patch)
      stats.rep_traj.append(res)
      verdict = _parse_review_verdict(res)
      if verdict == "APPROVE":
        stats.patch_report = res
        return False, patch  # Stop on review approval
    return True, res

  return agent.run(
    ENABLED_REPAIR_TOOLS,
    response_handler=response_callback,
    tool_call_handler=tool_call_callback,
  )


class ReportRootCauseTool(FuncToolBase):
  def __init__(self, acl: AccessControl, min_edit_point_lines: int):
    self.acl = acl
    self.min_edit_point_lines = min_edit_point_lines

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "report",
      "Stop process and report the found edit points for fixing the issue",
      [
        FuncToolSpec.Param(
          "edit_points",
          "list[tuple[int,int,string]]",
          True,
          "A list of edit points with each being a tuple of the one-indexed starting line number (included)"
          ", the ending line number (included), and the relative path of the file to edit (starting with llvm/).",
        ),
        FuncToolSpec.Param(
          "thoughts",
          "string",
          True,
          'The detailed thoughts for diagnosing the issue including step-by-step "'
          '1. Understanding the Issue", '
          '2. "Analyzing `opt`\'s Log", '
          '3. "Root Cause Analysis", '
          '4. "Proposed Edit Points(s)", and '
          '5. "Conclusion".',
        ),
      ],
    )

  def _call(self, *, edit_points: list[tuple[int, int, str]], thoughts: str) -> str:
    # Check and fix the model-provided edit points
    fixed_edit_points = []
    for ind, edit in enumerate(edit_points):
      if len(edit) != 3:
        raise FuncToolCallException(
          f"Each edit point must be a tuple of 3 elements (starting line number, ending line number, and the relative path of the file to edit): {edit}"
        )
      fixed_edit = []
      try:
        start_line = int(edit[0])
      except Exception:
        raise FuncToolCallException(
          f"The starting line number must be an integer, got {edit[0]} at edit_points[{ind}]: {edit}"
        )
      if start_line < 1:
        raise FuncToolCallException(
          f"The starting line number must be an one-indexed integer, got {start_line} at edit_points[{ind}]: {edit}"
        )
      fixed_edit.append(start_line)
      try:
        end_line = int(edit[1])
      except Exception:
        raise FuncToolCallException(
          f"The ending line number must be an integer, got {edit[1]} at edit_points[{ind}]: {edit}"
        )
      if end_line < 1:
        raise FuncToolCallException(
          f"The ending line number must be an one-indexed integer, got {end_line} at edit_points[{ind}]: {edit}"
        )
      if end_line - start_line + 1 < self.min_edit_point_lines:
        raise FuncToolCallException(
          f"An edit point must be at least {self.min_edit_point_lines} lines long, got {end_line - start_line + 1} lines at edit_points[{ind}]: {edit}"
        )
      fixed_edit.append(end_line)
      try:
        resolved = self.acl.check_readable_file(edit[2])
        fixed_edit.append(str(resolved.relative_to(self.acl.root)))
      except Exception as e:
        raise FuncToolCallException(
          f"Invalid file path for detected at edit_points[{ind}]: {edit}. {e}"
        )
      fixed_edit_points.append(tuple(fixed_edit))
    return json.dumps(
      {
        "edit_points": fixed_edit_points,
        "thoughts": thoughts,
      },
      indent=2,
    )


def run_mini_agent(
  rep: Reproducer,
  *,
  # Opt information
  opt_pass: str,
  opt_cmd: str,
  opt_log: str,
  # Debugger information
  debugger: DebuggerBase,
  backtrace: StackTrace,
  # Agent used
  agent: AgentBase,
  # Harness
  harness: Harness,
  # Statistics
  stats: RunStats,
) -> Optional[str]:
  agent.clear_history()

  #####################################################
  # The agent runs by:
  # 1. Analyze the issue first to reason about the root cause and propose potential edit points.
  # 2. Leverage the provided information to guide the patch generation.
  #####################################################

  # Reason about the root cause and propose potential edit points
  console.print("Analyzing the issue to gather required information ...")
  agent.append_user_message(
    PROMPT_REASON.format(
      pass_name=opt_pass,
      reprod_code=rep.file_path.read_text(),
      issue_symptom=rep.symptom,
      opt_cmd=opt_cmd,
      opt_log=opt_log,
      trans_point_file=str(backtrace[-1].file),
      trans_point_func=backtrace[-1].func,
      trans_point_stack="\n".join([str(it) for it in reversed(backtrace)]),
      min_edit_point_lines=MIN_EDIT_POINT_LINES,
    )
  )

  def response_handler(_: str) -> Tuple[bool, str]:
    ensure_tools_available(agent, ["report"])
    return True, (
      "Error: You are not calling any tool or your tool call format is incorrect. "
      "You should always continue with tool calling and correct tool call format. "
      "Please continue."
      " If you are done, call the `report` tool with the edit points."
      " If you already called the `report` tool, please check the format and try again."
    )

  def tool_call_handler(name: str, _: str, res: str) -> Tuple[bool, str]:
    ensure_tools_available(agent, ["report"])
    if name != "report":
      return True, res  # Continue the process
    try:
      # The report tool returns a parseable JSON string
      json.loads(res)
    except Exception:
      return (True, res)  # Continue the process with an error message
    return False, res  # Stop the process with the result

  response = agent.run(
    ENABLED_REASON_TOOLS,
    response_handler=response_handler,
    tool_call_handler=tool_call_handler,
  )

  # Parse the response to get potential edit points
  response = json.loads(response)
  edit_points = response.get("edit_points", [])
  reasoning_thoughts = response.get("thoughts", "")
  fixed_edit_points = []

  for edit_point in edit_points:
    try:
      edit_point_start, edit_point_end, edit_point_file = edit_point
      if not is_interesting_file(edit_point_file):
        console.print(f"Ignore non-interesting file {edit_point_file} for now.")
        continue
      edit_point_file = Path(edit_point_file)
      if edit_point_file.is_absolute():
        edit_point_file = edit_point_file.relative_to(harness.llvm_dir)
      fixed_edit_points.append(
        PatchEditPoint(int(edit_point_start), int(edit_point_end), edit_point_file)
      )
    except Exception as e:
      console.print(
        f"WARNING: skip edit point {edit_point} due to parse failure: {e}",
        color="yellow",
      )

  stats.reasoning = reasoning_thoughts
  stats.editpoints = [ep.as_tuple() for ep in fixed_edit_points]

  # Generate a patch and fix the issue according to the information
  return patch_and_fix(
    fixed_edit_points,
    reasoning_thoughts,
    rep=rep,
    agent=agent,
    harness=harness,
    stats=stats,
  )


def is_interesting_file(filename: str) -> bool:
  if "llvm/ADT" in filename or "llvm/Support" in filename:
    return False
  if filename.endswith(".cpp"):
    return True
  # This is not an always-safe operation (some bugs may happen in functions defined in header files)
  if filename.endswith(".h"):
    # Avoid modifying llvm/IR files to reduce the rebuild time.
    return "llvm/Transforms" in filename or "llvm/Analysis" in filename
  return False


def prepare_debugger(
  rep: Reproducer, *, harness: Harness
) -> Tuple[DebuggerBase, StackTrace]:
  debugger = harness.attach_debugger(rep.command)

  # Pause the debugger at the first transformation point or crash point
  bug_type = harness.fixenv.get_bug_type()
  breakpints = (
    ASSERTION_FUNCTION_LIST if bug_type == "crash" else TRANSFORMATION_FUNCTION_LIST
  )
  cached_breakpoint_file = os.path.join(
    str(harness.build_dir), "autofix_breakpoint_cache.txt"
  )
  cached_breakpoint = None
  if os.path.exists(cached_breakpoint_file):
    with open(cached_breakpoint_file, "r") as fin:
      cached_breakpoint = fin.read().strip()
    if cached_breakpoint:
      console.print(f"Using the cached breakpoint function: {cached_breakpoint}")
      breakpints = [cached_breakpoint]
  console.print("Reproducing the issue with debugger...")
  backtrace, breakpoint = debugger.run(
    harness.llvm_dir,
    breakpints,
    bug_type == "miscompilation",
    frame_limit=25,  # 25 frames should be enough
  )
  if not cached_breakpoint and breakpoint:
    console.print(f"The cached breakpoint function: {breakpoint}")
    with open(cached_breakpoint_file, "w") as fou:
      fou.write(breakpoint)

  if bug_type == "miscompilation":
    backtrace.pop()  # Pop out the topmost transformation function
    debugger.select_frame(
      backtrace[-1].func
    )  # Select the topmost frame for miscompilations

  return debugger, backtrace


def run_opt(
  rep: Reproducer,
  *,
  harness: Harness,
  backtrace: StackTrace,
):
  # We get the transformation pass and its bound analysis passes
  opt_pass, analy_pass = harness.llvmcode.resolve_pass_name(" ".join(rep.command))
  console.print(f"Transform pass: {opt_pass}")
  console.print(f"Analysis passes: {', '.join([str(ap) for ap in analy_pass])}")

  # We run opt with the reproducer to collect verbose log
  opt_args = rep.command[1:] + harness.llvmcode.resolve_pass_opts(opt_pass)
  for idx in range(len(opt_args)):
    if opt_args[idx].count("-passes="):
      opt_args[idx] = "--passes=" + ",".join(analy_pass + [opt_pass])
  opt_args.remove(str(rep.file_path))
  for ap in analy_pass:
    opt_args += harness.llvmcode.resolve_pass_opts(ap)
  opt_args.append(
    "--debug-only="
    + ",".join(
      harness.llvmcode.resolve_debug_types(set([frame.file for frame in backtrace]))
    )
  )

  bug_type = harness.fixenv.get_bug_type()

  console.print("Running opt with the reproducer to collect verbose log ...")
  console.print(f"Options: {opt_args}")
  # TODO: `lli` leverages return code to indicate the success or failure, rather than the output.
  opt_cmd, opt_log = harness.run_opt(
    rep.file_path,
    opt_args,
    check=bug_type != "crash",
    # Run opt with the reproducer and useful options
    env={
      "LLVM_DISABLE_CRASH_REPORT": "1",
      "LLVM_DISABLE_SYMBOLIZATION": "1",
    },
  )
  if bug_type == "crash" and "PLEASE submit a bug report to " in opt_log:
    # Ignore the stack trace from the crash report
    opt_log = opt_log[: opt_log.find("PLEASE submit a bug report to ")]
  opt_log = harness.sanitize_output(opt_log)
  console.printb(title="Opt Verbose Log", message=f"$ {opt_cmd}\n{opt_log}")

  return opt_pass, opt_cmd, opt_log


def get_enabled_skills(harness: Harness):
  return [
    (sk, MAX_TCS_GET_CONTEXT)
    for sk in harness.get_skills()
    if sk.name in ENABLED_SKILLS
  ]


def get_enabled_tools(harness: Harness):
  tools: list[tuple[FuncToolBase, int]] = []

  # Harness-provided tools: source-tree, build, env, and debugger tools.
  for tool in harness.make_tools():
    name = tool.name()
    if name not in ENABLED_TOOLS:
      continue
    if name in EDIT_AND_TEST_TOOLS:
      tools.append((tool, MAX_TCS_EDIT_AND_TEST))
    elif name in GET_CONTEXT_TOOLS:
      tools.append((tool, MAX_TCS_GET_CONTEXT))
    else:
      panic(f"Tool {name} does not have a defined tool call limit.")

  # Agent-specific: report tool.
  tools.append(
    (ReportRootCauseTool(harness.acl, MIN_EDIT_POINT_LINES), MAX_TCS_GET_CONTEXT)
  )

  return tools


def autofix(
  rep: Reproducer,
  *,
  harness: Harness,
  agent: AgentBase,
  stats: RunStats,
):
  # We use a debugger to help the agent understand the context
  debugger, backtrace = prepare_debugger(rep, harness=harness)
  stats.trans_point = backtrace[-1].as_tuple()

  # Run opt to get the optimization pass and the verbose log of the reproducer's execution
  # These information will help the agent understand the context better
  opt_pass, opt_cmd, opt_log = run_opt(
    rep, harness=harness, backtrace=backtrace.clone()
  )

  # The list of our tools and their call limits. 0 means allowing unlimited call.
  for to, th in get_enabled_tools(harness):
    agent.register_tool(to, th)

  # Load and register skills as callable tools
  for sk, th in get_enabled_skills(harness):
    assert (
      "bash" in agent.tools.list() and agent.tools.get_remaining_budget("bash") > 0
    ), "Skills require the bash tool to be enabled"
    agent.register_skill(sk, th)

  # Run the agent with all required information and tools
  return run_mini_agent(
    rep,
    opt_pass=opt_pass,
    opt_cmd=opt_cmd,
    opt_log=opt_log,
    debugger=debugger,
    backtrace=backtrace,
    agent=agent,
    harness=harness,
    stats=stats,
  )


def parse_args():
  parser = ArgumentParser(description="llvm-autofix (mini)")
  parser.add_argument(
    "--issue",
    type=str,
    required=True,
    help="The issue ID to fix.",
  )
  parser.add_argument(
    "--model",
    type=str,
    required=True,
    help="The LLM model to use for the agent.",
  )
  parser.add_argument(
    "--driver",
    type=str,
    default="openai",
    help="The LLM API driver to use (default: openai).",
    choices=["openai", "anthropic"],
  )
  parser.add_argument(
    "--stats",
    type=str,
    default=None,
    help="Path to save the generation statistics as a JSON file (default: None).",
  )
  parser.add_argument(
    "--debug",
    action="store_true",
    default=False,
    help="Enable debug mode for more verbose output (default: False).",
  )
  parser.add_argument(
    "--aggressive-testing",
    action="store_true",
    default=False,
    help="Use all Transforms and Analysis tests for testing patches (default: False).",
  )
  return parser.parse_args()


def main():
  harness.require_home_dir()

  args = parse_args()

  # Set up the console for output
  if args.debug:
    global console
    console = get_boxed_console(debug_mode=True)

  # Set up used LLMs and agents
  if args.driver == "openai":
    from harness.lms.openai_generic import GPTGenericAgent

    agent_class = GPTGenericAgent
  elif args.driver == "anthropic":
    from harness.lms.anthropic_generic import ClaudeGenericAgent

    agent_class = ClaudeGenericAgent
  else:
    panic(f"Unsupported LLM API driver: {args.driver}")

  agent = agent_class(
    args.model,
    temperature=AGENT_TEMPERATURE,
    top_p=AGENT_TOP_P,
    max_completion_tokens=AGENT_MAX_COMPLETION_TOKENS,
    reasoning_effort=AGENT_REASONINT_EFFORT,
    token_limit=AGENT_MAX_CONSUMED_TOKENS,
    round_limit=AGENT_MAX_CHAT_ROUNDS,
    debug_mode=args.debug,
  )

  # Set up saved statistics and output
  stats_path = None
  if args.stats:
    stats_path = Path(args.stats)
    if stats_path.exists():
      panic(f"Stats file {stats_path} already exists.")

  # --- Use Harness for LLVM setup and reproduction ---
  with Harness.from_issue(
    args.issue,
    cmake_args=ADDITIONAL_CMAKE_FLAGS,
    aggressive_testing=args.aggressive_testing,
  ) as h:
    bug_type = h.fixenv.get_bug_type()
    if bug_type not in ["crash", "miscompilation"]:
      panic(f"Unsupported bug type: {bug_type}")

    console.print(f"Issue ID: {args.issue}")
    console.print(f"Issue Type: {bug_type}")
    console.print(f"Issue Commit: {h.fixenv.get_base_commit()}")
    console.print(f"Issue Title: {h.fixenv.get_hint_issue()['title']}")
    console.print(f"Issue Labels: {h.fixenv.get_hint_issue()['labels']}")

    console.print("Building LLVM and try reproducing the issue ...")
    rep = h.reproduce()
    console.print("Issue reproduced successfully.")
    console.printb(title="Reproducer", message=rep.source)
    console.printb(
      title="Reproducing Log", message=f"$ {rep.raw_command}\n{rep.symptom}"
    )

    # Start analyzing and repairing the issue
    stats = RunStats(command=vars(args))
    stats.total_time_sec = time.time()
    try:
      stats.patch = autofix(
        rep,
        harness=h,
        agent=agent,
        stats=stats,
      )
      if not stats.patch:
        raise NoAvailablePatchFound("All efforts tried yet no available patches found.")
      # Post validation when necessary
      if not h.fixenv.use_entire_regression_test_suite:
        console.print("Post-validating the generated patch ...")
        passed, errmsg = h.post_validate()
        if not passed:
          stats.patch = None
          console.printb(title="Post-validation", message=errmsg)
          raise NoAvailablePatchFound("Post validation failed")
        console.print("Passed")
    except Exception as e:
      import traceback

      stats.error = type(e).__name__
      stats.errmsg = str(e)
      stats.traceback = traceback.format_exc()

      raise e
    finally:
      stats.chat_rounds = agent.chat_stats["chat_rounds"]
      stats.input_tokens = agent.chat_stats["input_tokens"]
      stats.output_tokens = agent.chat_stats["output_tokens"]
      stats.cached_tokens = agent.chat_stats["cached_tokens"]
      stats.total_tokens = agent.chat_stats["total_tokens"]
      stats.total_time_sec = time.time() - stats.total_time_sec
      if stats_path:
        with stats_path.open("w") as fout:
          json.dump(stats.as_dict(), fout, indent=2)
        console.print(f"Generation statistics saved to {stats_path}.")

    console.print("Final Patch")
    console.print("-----------")
    console.print(stats.patch)
    console.print("Reference Patch")
    console.print("---------------")
    console.print(h.fixenv.get_reference_patch())
    console.print("Statistics")
    console.print("----------")
    console.print(json.dumps(stats.as_dict(), indent=2))


if __name__ == "__main__":
  main()
