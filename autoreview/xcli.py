import os
import shlex
import shutil
import subprocess
from argparse import ArgumentParser
from pathlib import Path
from typing import Optional

from autofix.llvm.lab_env import Environment as FixEnvironment
from autofix.llvm.llvm_helper import (
  apply as apply_patch_to_llvm,
)
from autofix.llvm.llvm_helper import (
  get_first_failed_test,
  get_llvm_build_dir,
  llvm_dir,
  pretty_render_log,
  set_llvm_build_dir,
)
from autofix.mini import ADDITIONAL_CMAKE_FLAGS
from autofix.utils import cmdline

LLVM_AUTOFIX_HOME_DIR = os.environ.get("LLVM_AUTOFIX_HOME_DIR")

PROMPT_TEMPLATE = """Review the following patch for fixing the given issue.

## Patch to Review

```diff
{patch_diff}
```

## Issue Reproduction

Type: {issue_type}

Reproducer (LLVM IR): ```bash
cat {issue_rep_path}
{issue_rep_code}
```

LLVM's Symptom: ```bash
{issue_command}
{issue_symptom}
```

## Information

- The root directory of the LLVM project is: {workdir}
- The build directory is: {builddir}

## Workflow

1. Use the `patch-review` skill to review the patch and generate a review report.
2. Save the generated review report into {report_path}.
3. You are done.
"""


def panic(msg: str):
  print(f"Error: {msg}")
  exit(1)


def parse_args():
  parser = ArgumentParser(description="Wrapper of XXX CLI/Agent (llvm-autoreview)")
  parser.add_argument(
    "--issue",
    type=str,
    required=True,
    help="The issue ID to fix.",
  )
  parser.add_argument(
    "--patch",
    type=str,
    required=True,
    help="Path to save the generated patch in a unified diff format.",
  )
  parser.add_argument(
    "--xcli",
    type=str,
    required=True,
    choices=["claudecode", "codex", "geminicli"],
    help="The XXX CLI/Agent to use for fixing the issue.",
  )
  parser.add_argument(
    "--model",
    type=str,
    default=None,
    help="The LLM model to use for the agent.",
  )
  parser.add_argument(
    "--output",
    type=str,
    required=True,
    help="Path to save the generated review report.",
  )
  return parser.parse_args()


def ensure_xcli_exists(xcli: str):
  bin = {
    "claudecode": "claude",
    "geminicli": "gemini",
  }.get(xcli, "unknown")
  if bin == "unknown":
    panic(f"Unsupported X-CLI: {xcli}")
  if not shutil.which(bin):
    panic(f"The `{bin}` command is not found.")


def render_xcli_command(
  xcli: str,
  *,
  prompt: str,
  session: Optional[str] = None,
  model: Optional[str] = None,
) -> str:
  # TODO: Output the trajectory in a structured format
  if xcli == "claudecode":
    model_arg = f"--model {model}" if model else ""
    session_arg = f"--session-id {session}" if session else ""
    return f"claude --dangerously-skip-permissions --verbose --output-format stream-json {model_arg} {session_arg} -p {shlex.quote(prompt)}"
  elif xcli == "geminicli":
    model_arg = f"--model {model}" if model else ""
    # Session is not supported in Gemini CLI
    print(
      "Warning: Session is not supported in Gemini CLI, ignoring the session argument."
    )
    return (
      f"gemini --yolo --output-format stream-json {model_arg} -p {shlex.quote(prompt)}"
    )
  # TODO: Support Codex
  raise ValueError(f"Unsupported X-CLI: {xcli}")


def main():
  if LLVM_AUTOFIX_HOME_DIR is None:
    panic("The llvm-autofix environment has not been brought up.")

  args = parse_args()

  ensure_xcli_exists(args.xcli)

  output_path = Path(args.output).resolve().absolute()
  if output_path.exists():
    panic(f"Output file {args.output} already exists.")
  # We save the model's trajectory in a seprate file
  traj_path = output_path.with_suffix(".traj.jsonl")
  if traj_path.exists():
    panic(f"Trajectory file {traj_path} already exists.")

  patch_path = Path(args.patch).resolve().absolute()
  if not patch_path.exists():
    panic(f"The patch file {args.patch} does not exist.")
  patch_diff = patch_path.read_text()

  print("Setting up LLVM environment ...")
  issue = args.issue
  set_llvm_build_dir(os.path.join(get_llvm_build_dir(), issue))
  fixenv = FixEnvironment(
    issue,
    base_model_knowledge_cutoff="2023-12-31Z",
    additional_cmake_args=ADDITIONAL_CMAKE_FLAGS,
    max_build_jobs=os.environ.get("LLVM_AUTOFIX_MAX_BUILD_JOBS"),
    use_entire_regression_test_suite=False,
  )
  fixenv.reset()
  print("LLVM environment is ready.")

  print("Building LLVM and try reproducing the issue ...")
  check_failed, check_log = fixenv.check_fast()
  if check_failed:
    panic(f"Failed to build or reproduce the issue. Please try again.\n\n{check_log}")
  reprod_data = get_first_failed_test(check_log)
  reprod_args = reprod_data["args"]
  reprod_code = reprod_data["body"]
  reprod_log = pretty_render_log(reprod_data["log"])
  print("Issue reproduced successfully.")
  reprod_file = os.path.join("/", "tmp", f"test_{issue}.ll")
  with open(reprod_file, "w") as fou:
    fou.write(reprod_code)

  print("Applying the patch to LLVM and test if the issue is fixed ...")
  apply_patch_to_llvm(patch_diff)
  res, _ = fixenv.check_pass()
  if not res:
    panic("The patch does not fix the original issue.")
  print("Patch applied and issue fixed successfully.")

  print(f"Preparing {args.xcli} command to reviewing the LLVM patch ...")
  prompt = PROMPT_TEMPLATE.format(
    patch_diff=patch_diff,
    issue_type=fixenv.get_bug_type(),
    issue_rep_path=reprod_file,
    issue_rep_code=reprod_code,
    issue_command=" ".join(
      list(
        filter(
          lambda x: x != "",
          reprod_args.replace("< ", " ")
          .replace("%s", reprod_file)
          .replace("2>&1", "")
          .replace("'", "")
          .replace('"', "")
          .replace("opt", os.path.join(get_llvm_build_dir(), "bin", "opt"), 1)
          .strip()
          .split(" "),
        )
      )
    ),
    issue_symptom=reprod_log,
    workdir=llvm_dir,
    builddir=get_llvm_build_dir(),
    report_path=output_path,
  )
  command = render_xcli_command(
    args.xcli,
    prompt=prompt,
    model=args.model,
  )
  print(f"Agent command prepared: {command[:80]} ...")

  # Run the agent command to review the patch.
  print("Starting to review the patch ...")
  try:
    cmdline.redirect_stdout(
      command,
      stdout=str(traj_path),
      timeout=1800,
      check=True,
      env=os.environ.copy(),
    )
    print("Review finished successfully.")
    print(f"The report was saved to {output_path}.")
  except subprocess.CalledProcessError as e:
    err_msg = e.stderr.decode() if e.stderr else ""
    print(f"Review failed with error message:\n{err_msg}")
    raise e


if __name__ == "__main__":
  main()
