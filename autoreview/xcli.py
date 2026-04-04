import os
import shlex
import shutil
import subprocess
from argparse import ArgumentParser
from pathlib import Path
from typing import Optional

import yaml

from autofix.mini import ADDITIONAL_CMAKE_FLAGS
from harness.llvm.harness import Harness
from harness.utils import cmdline

LLVM_HARNESS_HOME_DIR = os.environ.get("LLVM_HARNESS_HOME_DIR")

PROMPT_TEMPLATE = yaml.safe_load(
  Path(
    os.path.join(
      os.environ.get("LLVM_HARNESS_HOME_DIR", "."), "autoreview", "xcli.yaml"
    )
  ).read_text()
)["prompt"]


def panic(msg: str):
  print(f"Error: {msg}")
  exit(1)


def parse_args():
  parser = ArgumentParser(description="Wrapper of XXX CLI/Agent (llvm-autoreview)")
  parser.add_argument(
    "--issue",
    type=str,
    required=True,
    help="The issue ID to review.",
  )
  parser.add_argument(
    "--patch",
    type=str,
    required=True,
    help="Path to the patch file in unified diff format.",
  )
  parser.add_argument(
    "--xcli",
    type=str,
    required=True,
    choices=["claudecode", "geminicli"],
    help="The XXX CLI/Agent to use for reviewing the patch.",
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
  bin_name = {
    "claudecode": "claude",
    "geminicli": "gemini",
  }.get(xcli, "unknown")
  if bin_name == "unknown":
    panic(f"Unsupported X-CLI: {xcli}")
  if not shutil.which(bin_name):
    panic(f"The `{bin_name}` command is not found.")


def render_xcli_command(
  xcli: str,
  *,
  prompt: str,
  session: Optional[str] = None,
  model: Optional[str] = None,
) -> tuple[str, str]:
  if xcli == "claudecode":
    model_arg = f"--model {model}" if model else ""
    session_arg = f"--session-id {session}" if session else ""
    return (
      f"claude --dangerously-skip-permissions --verbose --output-format stream-json {model_arg} {session_arg} -p {shlex.quote(prompt)}",
      ".claude",
    )
  elif xcli == "geminicli":
    model_arg = f"--model {model}" if model else ""
    print(
      "Warning: Session is not supported in Gemini CLI, ignoring the session argument."
    )
    return (
      f"gemini --yolo --output-format stream-json {model_arg} -p {shlex.quote(prompt)}"
    ), ".gemini"
  # TODO: Support Codex
  raise ValueError(f"Unsupported X-CLI: {xcli}")


def main():
  if LLVM_HARNESS_HOME_DIR is None:
    panic("The llvm-harness environment has not been brought up.")

  args = parse_args()

  ensure_xcli_exists(args.xcli)

  output_path = Path(args.output).resolve().absolute()
  if output_path.exists():
    panic(f"Output file {args.output} already exists.")
  traj_path = output_path.with_suffix(".traj.jsonl")
  if traj_path.exists():
    panic(f"Trajectory file {traj_path} already exists.")

  patch_path = Path(args.patch).resolve().absolute()
  if not patch_path.exists():
    panic(f"The patch file {args.patch} does not exist.")
  patch_diff = patch_path.read_text()

  with Harness.from_issue(
    args.issue,
    cmake_args=ADDITIONAL_CMAKE_FLAGS,
  ) as h:
    print("Building LLVM and try reproducing the issue ...")
    issue = h.reproduce()
    print("Issue reproduced successfully.")

    print("Applying the patch to LLVM and test if the issue is fixed ...")
    ok, log = h.apply_patch(patch_diff)
    if not ok:
      panic(f"Failed to apply patch:\n{log}")
    ok, log = h.fixenv.check_pass()
    if not ok:
      panic(f"The patch does not fix the original issue:\n{log}")
    print("Patch applied and issue fixed successfully.")

    print(f"Preparing {args.xcli} command to review the LLVM patch ...")
    prompt = PROMPT_TEMPLATE.format(
      patch_diff=patch_diff,
      issue_type=issue.bug_type,
      issue_rep_path=str(issue.file_path),
      issue_rep_code=issue.source,
      issue_command=" ".join(issue.command),
      issue_symptom=issue.symptom,
      llvm_dir=str(h.llvm_dir),
      build_dir=str(h.build_dir),
      report_path=output_path,
    )
    command, xcli_dirname = render_xcli_command(
      args.xcli,
      prompt=prompt,
      model=args.model,
    )
    print(f"Agent command prepared: {command[:80]} ...")

    # Prepare and install the skill into the cli's skill directory.
    workdir = Path.cwd()
    h.install_skill("llvm-patchreview", workdir / xcli_dirname)

    # Run the agent command to review the patch.
    print("Starting to review the patch ...")
    try:
      cmdline.redirect_stdout(
        command,
        stdout=str(traj_path),
        timeout=1800,
        check=True,
        cwd=workdir,
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
