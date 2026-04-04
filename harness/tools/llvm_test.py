from typing import Optional, Tuple

from unidiff import PatchedFile, PatchSet

from harness.llvm.intern.lab_env import FixEnv
from harness.llvm.intern.llvm import get_first_failed_test, pretty_render_log
from harness.lms.tool import FuncToolCallException, FuncToolSpec, StatelessFuncToolBase


# TODO: Test sufficiency is a problem in any agents and benchmarks.
# For ours, we used: (1) the reproducer, (2) pass-specific regression tests, and (3) weak assertion checks.
# Yet, this is not sufficient since
# * The agent may patches that weaken the assertion
# * The agent may generate conditions to bypass the pass
# * The agent may generate code that invalidates other passes
# Thus, we need more integral yet minimal tests for example
# (1) better assertion or condition checks
# (2) run Csmith for a while
# (3) design more applicable regression tests or leverage existing test suites
# (4) etc.
class TestTool(StatelessFuncToolBase):
  def __init__(self, env: FixEnv, allow_alt_asserts: bool = False):
    self.env = env
    self.allow_alt_asserts = allow_alt_asserts

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "test",
      "Build LLVM with your changes, verify the original bug is fixed, and run regression tests. "
      "Use this when you believe your patch is ready — it rebuilds and runs the full test suite, so it is expensive. "
      "Check the output carefully: a failure means the patch is incorrect or introduces regressions.",
      [],
    )

  def is_valid_patches(self, patches: PatchSet) -> Tuple[bool, Optional[str]]:
    for patch in patches:
      valid, errmsg = self.is_valid_patch(patch)
      if not valid:
        return False, errmsg
    return True, None

  def is_valid_patch(self, patch: PatchedFile) -> Tuple[bool, Optional[str]]:
    if self.allow_alt_asserts:
      return True, None  # Skip checks if assertions are allowed.
    # TODO: It is likely that the patch modifies assertions but `assert` does not present in the patch.
    # Assertions are not allowed to be altered anyway.
    removed_asserts = []
    added_asserts = []
    for hunk in patch:
      for line in hunk:
        if "assert" in line.value:
          if line.is_removed:
            removed_asserts.append(line.value.strip())
          elif line.is_added:
            added_asserts.append(line.value.strip())
    for line in removed_asserts:
      # Assertions may be altered due to format issue.
      # Bail out on this case.
      if line not in added_asserts:
        return (
          False,
          "There're modifications to assertions while assertions are not allowed to be modified in anyway.",
        )
    return True, None

  def normalize_feedback(self, log) -> str:
    if not isinstance(log, list):
      return str(log)
    return pretty_render_log(get_first_failed_test(log))

  def _call(self, **kwargs) -> str:
    try:
      changes = self.env.dump_patch()
      patches = PatchSet(changes)
      if not patches:
        raise FuncToolCallException(
          "No patches found. Before testing, please preview your changes first."
        )
    except Exception as e:
      raise FuncToolCallException(str(e))
    valid, errmsg = self.is_valid_patches(patches)
    if not valid:
      changes += "\n" if not changes.endswith("\n") else ""
      raise FuncToolCallException(
        f"Patch validation failure: {errmsg}.\n"
        "Below are your *invalid* changes:\n"
        "--------\n"
        f"{changes}"
        "--------"
      )
    res, log = self.env.check_pass()
    if res:
      return "<success>"
    return "FAILURE\n\n" + (self.normalize_feedback(log))
