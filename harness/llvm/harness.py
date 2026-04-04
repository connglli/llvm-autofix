from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired
from typing import TYPE_CHECKING

from harness.llvm.access import AccessControl
from harness.llvm.intern import llvm as llvm_ops
from harness.utils import cmdline

if TYPE_CHECKING:
  from harness.llvm.debugger import DebuggerBase
  from harness.llvm.intern.lab_env import FixEnv
  from harness.llvm.intern.llvm_code import LlvmCode
  from harness.lms.tool import FuncToolBase


@dataclass
class Reproducer:
  """Result of reproducing a bug — either from bench/ or ad-hoc."""

  issue_id: str
  bug_type: str  # "crash" | "miscompilation" | "hang"
  file_path: Path  # path to written .ll file
  command: list[str]  # resolved opt command tokens
  raw_command: str  # original unresolved command string
  source: str  # IR reproducer text
  symptom: str  # rendered log output


def _parse_raw_command(raw_cmd: str, reprod_file: str, opt_binary: str) -> list[str]:
  """Turn an opt test command template into a resolved command list.

  This consolidates the duplicated command-string construction from
  mini.py / mswe.py / xcli.py / autoreview.
  """
  return list(
    filter(
      lambda x: x != "",
      raw_cmd.replace("< ", " ")
      .replace("%s", reprod_file)
      .replace("2>&1", "")
      .replace("'", "")
      .replace('"', "")
      .replace("opt", opt_binary, 1)
      .strip()
      .split(" "),
    )
  )


def _make_temp_ll(issue_id: str, content: str) -> Path:
  """Write *content* to a uniquely-named temp ``.ll`` file and return its path."""
  fd, path = tempfile.mkstemp(suffix=".ll", prefix=f"reprod_{issue_id}_")
  try:
    os.write(fd, content.encode())
  finally:
    os.close(fd)
  return Path(path)


class Harness:
  """Configured LLVM workspace — the single entry point for harness consumers.

  Paths (``llvm_dir``, ``build_dir``) are managed by the lowest layer
  (``intern/llvm.py``) which loads them from environment variables.
  The Harness reads from that single source of truth.

  Use one of the factory methods to create an instance:

  * :meth:`workspace` — bare LLVM workspace (superopt, general dev)
  * :meth:`from_issue` — bench issue from ``bench/``
  * :meth:`from_reproducer` — ad-hoc bug from a user-provided file
  """

  def __init__(
    self,
    *,
    acl: AccessControl | None = None,
    # Bench-issue fields (set by from_issue)
    fixenv: FixEnv | None = None,
    issue_id: str | None = None,
    # Ad-hoc issue fields (set by from_reproducer)
    reproducer_file: str | None = None,
    reproducer_command: str | None = None,
    reproducer_bug_type: str | None = None,
  ):
    self.acl = acl or AccessControl(self.llvm_dir)
    self.fixenv: FixEnv | None = fixenv
    self._issue_id = issue_id
    self._llvmcode: LlvmCode | None = None
    self._debugger: DebuggerBase | None = None

    # Ad-hoc reproducer state
    self._reproducer_file = reproducer_file
    self._reproducer_command = reproducer_command
    self._reproducer_bug_type = reproducer_bug_type

  # -------------------------------------------------------------------
  # Paths — delegated to intern/llvm.py (single source of truth)
  # -------------------------------------------------------------------

  @property
  def llvm_dir(self) -> Path:
    """Root of the LLVM source tree."""
    return Path(llvm_ops.llvm_dir).resolve()

  @property
  def build_dir(self) -> Path:
    """Current LLVM build directory."""
    return Path(llvm_ops.get_llvm_build_dir()).resolve()

  @property
  def alive_tv(self) -> str | None:
    """Path to the alive-tv binary, or ``None`` if not configured."""
    return llvm_ops.llvm_alive_tv

  @property
  def llvmcode(self) -> LlvmCode:
    """Lazily-created :class:`LlvmCode` for LLVM source analysis."""
    if self._llvmcode is None:
      from harness.llvm.intern.llvm_code import LlvmCode as _LlvmCode

      self._llvmcode = _LlvmCode()
    return self._llvmcode

  # -------------------------------------------------------------------
  # LLVM Operations
  # -------------------------------------------------------------------

  def run_opt(
    self, file, args: list[str], *, check: bool = True, **kwargs
  ) -> tuple[str, str]:
    """Run ``opt`` on *file* with *args* and return ``(command, output)``."""
    opt = self.build_dir / "bin" / "opt"
    cmd = " ".join([str(opt.absolute())] + args + [str(Path(file).absolute())])
    return cmd, cmdline.getoutput(cmd, check=check, **kwargs).decode()

  # -------------------------------------------------------------------
  # Debugger
  # -------------------------------------------------------------------

  @property
  def debugger(self) -> DebuggerBase | None:
    """The attached debugger, or ``None``."""
    return self._debugger

  def attach_debugger(self, command: list[str]) -> DebuggerBase:
    """Create and attach a GDB debugger with the given command."""
    from harness.llvm.gdb_support import GDB

    self._debugger = GDB(command)
    return self._debugger

  # -------------------------------------------------------------------
  # Factory methods
  # -------------------------------------------------------------------

  @staticmethod
  def workspace(
    *,
    editable: list[str] | None = None,
    readable: list[str] | None = None,
    ignored: list[str] | None = None,
  ) -> Harness:
    """Create a bare LLVM workspace (superopt, general dev)."""
    root = Path(llvm_ops.llvm_dir).resolve()
    acl = AccessControl(root, editable=editable, readable=readable, ignored=ignored)
    return Harness(acl=acl)

  @staticmethod
  def from_issue(
    issue_id: str,
    *,
    cmake_args: list[str] | None = None,
    max_build_jobs: int | None = None,
    max_test_jobs: int | None = None,
    aggressive_testing: bool = False,
    model_knowledge_cutoff: str = "2023-12-31Z",
    editable: list[str] | None = None,
    readable: list[str] | None = None,
    ignored: list[str] | None = None,
  ) -> Harness:
    """Create a harness for a bench issue from ``bench/``."""
    from harness.llvm.intern.lab_env import FixEnv

    root = Path(llvm_ops.llvm_dir).resolve()
    acl = AccessControl(root, editable=editable, readable=readable, ignored=ignored)
    env = FixEnv(
      issue_id,
      base_model_knowledge_cutoff=model_knowledge_cutoff,
      additional_cmake_args=cmake_args or [],
      max_build_jobs=max_build_jobs or os.environ.get("LLVM_HARNESS_MAX_BUILD_JOBS"),
      max_test_jobs=max_test_jobs,
      use_entire_regression_test_suite=aggressive_testing,
    )
    return Harness(
      acl=acl,
      fixenv=env,
      issue_id=issue_id,
    )

  @staticmethod
  def from_reproducer(
    file: str | Path,
    command: str,
    bug_type: str,
    *,
    editable: list[str] | None = None,
    readable: list[str] | None = None,
    ignored: list[str] | None = None,
  ) -> Harness:
    """Create a harness for an ad-hoc bug from a user-provided file."""
    root = Path(llvm_ops.llvm_dir).resolve()
    acl = AccessControl(root, editable=editable, readable=readable, ignored=ignored)
    return Harness(
      acl=acl,
      reproducer_file=str(file),
      reproducer_command=command,
      reproducer_bug_type=bug_type,
    )

  # -------------------------------------------------------------------
  # Context manager
  # -------------------------------------------------------------------

  def __enter__(self) -> Harness:
    # For bench issues, set build dir to a per-issue subdirectory and reset the repo.
    if self._issue_id:
      llvm_ops.set_llvm_build_dir(
        os.path.join(llvm_ops.get_llvm_build_dir(), self._issue_id)
      )
      self._reset_with_retry()

    return self

  def __exit__(self, *exc):
    pass

  def _reset_with_retry(self):
    try:
      self.fixenv.reset()
    except Exception:
      # Sync and retry once.
      llvm_ops.reset("main")
      llvm_ops.git_execute(["pull", "origin", "main"])
      self.fixenv.reset()

  # -------------------------------------------------------------------
  # Operations
  # -------------------------------------------------------------------

  def build(self) -> tuple[bool, str]:
    """Build LLVM. Delegates to ``fixenv.build()`` if available, otherwise
    calls the raw build function directly."""
    if self.fixenv is not None:
      return self.fixenv.build()

    return llvm_ops.build(
      max_build_jobs=os.cpu_count(),
    )

  def post_validate(self) -> tuple[bool, str]:
    """Run full regression tests to validate a patch.

    Temporarily enables the entire regression test suite, runs midend +
    regression-diff checks, then restores the original setting.

    Returns ``(passed, errmsg)``.
    """
    if self.fixenv is None:
      return True, "No fixenv configured, skipping post-validation."
    backup_val = self.fixenv.use_entire_regression_test_suite
    self.fixenv.use_entire_regression_test_suite = True
    try:
      passed, errmsg = self.fixenv.check_midend()
      if passed:
        passed, errmsg = self.fixenv.check_regression_diff()
      return passed, errmsg
    finally:
      self.fixenv.use_entire_regression_test_suite = backup_val

  def reproduce(self) -> Reproducer:
    """Reproduce the configured bug and return a :class:`Reproducer`.

    For bench issues this builds LLVM and runs the reproducer tests.
    For ad-hoc issues this runs the given command on the given file.
    """
    if self.fixenv is not None:
      return self._reproduce_bench()
    if self._reproducer_file is not None:
      return self._reproduce_adhoc()
    raise RuntimeError(
      "No issue configured. Use Harness.from_issue() or Harness.from_reproducer()."
    )

  def _reproduce_bench(self) -> Reproducer:
    check_failed, check_log = self.fixenv.check_fast()
    if check_failed:
      raise RuntimeError(f"Failed to build or reproduce the issue.\n\n{check_log}")

    reprod_data = llvm_ops.get_first_failed_test(check_log)
    raw_cmd = reprod_data["args"]
    reprod_code = reprod_data["body"]
    reprod_log = llvm_ops.pretty_render_log(reprod_data["log"])

    # Write the reproducer IR to a uniquely-named temp file.
    reprod_file = _make_temp_ll(self._issue_id, reprod_code)

    opt_binary = str(self.build_dir / "bin" / "opt")
    command = _parse_raw_command(raw_cmd, str(reprod_file), opt_binary)

    return Reproducer(
      issue_id=self._issue_id,
      bug_type=self.fixenv.get_bug_type(),
      file_path=reprod_file,
      command=command,
      raw_command=raw_cmd,
      source=reprod_code,
      symptom=reprod_log,
    )

  def _reproduce_adhoc(self) -> Reproducer:
    reprod_file = Path(self._reproducer_file).resolve()
    if not reprod_file.exists():
      raise FileNotFoundError(f"Reproducer file not found: {reprod_file}")

    opt_binary = str(self.build_dir / "bin" / "opt")
    command = _parse_raw_command(self._reproducer_command, str(reprod_file), opt_binary)

    # Run the command to verify the bug manifests.
    cmd_str = " ".join(command)
    try:
      output = cmdline.getoutput(cmd_str, check=True, timeout=60)
      symptom = output.decode(errors="replace")

      if self._reproducer_bug_type == "crash":
        # If check=True didn't raise, opt exited 0 — unexpected for a crash.
        if not llvm_ops.is_opt_crash(symptom):
          raise RuntimeError(
            f"Expected crash but opt exited normally.\n\noutput:\n{symptom}"
          )
    except CalledProcessError as e:
      stderr = e.stderr.decode(errors="replace") if e.stderr else ""
      stdout = e.stdout.decode(errors="replace") if e.stdout else ""
      symptom = stderr or stdout or str(e)
    except TimeoutExpired:
      if self._reproducer_bug_type != "hang":
        raise
      symptom = "Process timed out (hang detected)."

    return Reproducer(
      issue_id="adhoc",
      bug_type=self._reproducer_bug_type,
      file_path=reprod_file,
      command=command,
      raw_command=self._reproducer_command,
      source=reprod_file.read_text(),
      symptom=symptom,
    )

  # -------------------------------------------------------------------
  # Git operations
  # -------------------------------------------------------------------

  def git(self, *args: str) -> str:
    """Run a git command in the LLVM source directory."""
    return llvm_ops.git_execute(list(args))

  def checkout(self, ref: str):
    """Checkout a git ref in the LLVM source directory."""
    self.git("checkout", ref)

  def reset_state(self):
    """Reset the LLVM source directory to a clean state."""
    llvm_ops.reset()

  def apply_patch(self, patch: str) -> tuple[bool, str]:
    """Apply a unified diff patch to the LLVM source tree."""
    return llvm_ops.apply_patch(patch)

  def sanitize_output(self, output: str) -> str:
    """Strip absolute LLVM paths from *output* for safe display to agents."""
    return llvm_ops.remove_path_from_output(output)

  # -------------------------------------------------------------------
  # Skills
  # -------------------------------------------------------------------

  def get_skills(self) -> list[Path]:
    """All available skill directories (auto-discovered)."""
    from harness.skills import list_skills

    return list_skills()

  def get_skill(self, name: str) -> Path:
    """Return the path of a skill by directory name.

    Raises :class:`KeyError` if the skill is not found.
    """
    for sk in self.get_skills():
      if sk.name == name:
        return sk
    available = [sk.name for sk in self.get_skills()]
    raise KeyError(
      f"Skill {name!r} not found. Available skills: {', '.join(available)}"
    )

  def install_skill(self, name: str, path: Path, exists_ok: bool = False):
    """Install a skill into *path*/skills under the name *name*."""

    skill_path = self.get_skill(name)

    target_path = path / "skills"
    target_path.mkdir(exist_ok=True)

    target_skill_path = target_path / name
    if target_skill_path.exists():
      if not exists_ok:
        raise FileExistsError(
          f"Target skill path {target_skill_path} already exists. Set exists_ok=True to overwrite."
        )
      if target_skill_path.is_symlink() or target_skill_path.is_file():
        target_skill_path.unlink()
      elif target_skill_path.is_dir():
        import shutil

        shutil.rmtree(target_skill_path)
    target_skill_path.symlink_to(skill_path, target_is_directory=True)

  # -------------------------------------------------------------------
  # Tools
  # -------------------------------------------------------------------

  def make_tools(self) -> list[FuncToolBase]:
    """Instantiate all tools available given the current harness state.

    Tools are gated by available dependencies:

    * Always (llvm_dir): read, list, find, ripgrep, edit, write, bash
    * build_dir present: optimize_ir, compile_ir, interpret_ir, verify_ir
    * fixenv present (bench issue): test, reset, preview, langref
    * debugger attached: code, docs, debug, eval
    """
    tools: list[FuncToolBase] = []

    # -- Always available (source-tree tools) --
    from harness.tools.edit import EditTool
    from harness.tools.findn import FindNTool
    from harness.tools.listn import ListNTool
    from harness.tools.readn import ReadNTool
    from harness.tools.ripgrepn import RipgrepNTool
    from harness.tools.write import WriteTool

    tools.append(ReadNTool(self.acl))
    tools.append(ListNTool(self.acl))
    tools.append(FindNTool(self.acl))
    tools.append(RipgrepNTool(self.acl))
    tools.append(EditTool(self.acl))
    tools.append(WriteTool(self.acl))

    # Bash is always available but not scoped by ACL at the file level.
    from harness.tools.bash import BashTool

    tools.append(BashTool(self.acl))

    # -- Build-dir tools --
    build_dir = str(self.build_dir)
    try:
      from harness.tools.llvm_llc import CompileIrTool
      from harness.tools.llvm_lli import InterpretIrTool
      from harness.tools.llvm_opt import OptimizeIrTool

      tools.append(OptimizeIrTool(build_dir))
      tools.append(InterpretIrTool(build_dir))
      tools.append(CompileIrTool(build_dir))
    except Exception:
      pass  # Binaries not built yet

    if self.alive_tv:
      try:
        from harness.tools.llvm_alive2 import VerifyIrTool

        tools.append(VerifyIrTool(self.alive_tv))
      except Exception:
        pass  # alive-tv not available

    # -- Env-dependent tools (bench issue) --
    if self.fixenv is not None:
      from harness.tools.llvm_langref import LangRefTool
      from harness.tools.llvm_preview import PreviewTool
      from harness.tools.llvm_reset import ResetTool
      from harness.tools.llvm_test import TestTool

      tools.append(TestTool(self.fixenv))
      tools.append(ResetTool(self.acl, self.fixenv.base_commit))
      tools.append(PreviewTool(self.fixenv))
      tools.append(LangRefTool(self.fixenv))

    # -- Debugger-dependent tools --
    if self._debugger is not None:
      from harness.tools.llvm_code import CodeTool
      from harness.tools.llvm_debug import DebugTool
      from harness.tools.llvm_docs import DocsTool
      from harness.tools.llvm_eval import EvalTool

      tools.append(CodeTool(self.llvmcode, self._debugger))
      tools.append(DocsTool(self.llvmcode, self._debugger))
      tools.append(DebugTool(self._debugger))
      tools.append(EvalTool(self._debugger))

    return tools

  def make_tool(self, name: str) -> FuncToolBase:
    """Instantiate a single tool by name.

    Raises :class:`KeyError` if the tool is not available.
    """
    tools = self.make_tools()
    for tool in tools:
      if tool.name() == name:
        return tool
    available = [t.name() for t in tools]
    raise KeyError(
      f"Tool {name!r} not available. Available tools: {', '.join(available)}"
    )
