import shlex
from subprocess import CalledProcessError

from harness.llvm.access import AccessControl
from harness.lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from harness.utils import bashlex, cmdline

# TODO: add other tools that do not require permission
FORBIDDEN_TOOLS = [
  "which",
  "sudo",
  "rm",
  "curl",
  "wget",
  "git",
  "ssh",
  "scp",
  "ftp",
  "telnet",
  "ping",
  "traceroute",
  "nslookup",
  "dig",
  "nmap",
  "apt",
  "apt-get",
  "dpkg",
]


class BashTool(FuncToolBase):
  def __init__(self, acl: AccessControl):
    self.acl = acl

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "bash",
      "Execute a bash command in the llvm/ directory. "
      "This tool should be used for commands that are not provided by other tools, "
      "such as building the project, running specific tests, or using complex shell commands with pipes and redirections.",
      [
        FuncToolSpec.Param(
          "command",
          "string",
          True,
          "The bash command to execute.",
        ),
        FuncToolSpec.Param(
          "timeout",
          "integer",
          False,
          "Optional timeout in seconds for the command execution. Default is 60 seconds.",
        ),
      ],
    )

  def _call(self, *, command: str, timeout: int = 60, **kwargs) -> str:
    if not command:
      raise FuncToolCallException(
        "No command provided. Please specify the bash command to execute."
      )

    # Check for forbidden tools in the command to prevent unauthorized actions.
    for cmd in bashlex.get_commands(command):
      if cmd in FORBIDDEN_TOOLS:
        raise FuncToolCallException(
          f"You do not have permission to use command `{cmd}`."
        )

    # We use 'bash -c' to ensure full shell support (pipes, redirects, etc.)
    bash_cmd = f"bash -c {shlex.quote(command)}"

    try:
      output = cmdline.getoutput(
        bash_cmd, cwd=self.acl.root, check=True, timeout=timeout
      )
      return output.decode("utf-8")
    except CalledProcessError as e:
      # If the command failed, return the combined output and error message.
      error_output = e.stdout.decode("utf-8") if e.stdout else ""
      raise FuncToolCallException(
        f"Command failed with exit code {e.returncode}.\n\nOutput:\n{error_output}"
      )
    except Exception as e:
      raise FuncToolCallException(f"Failed to execute command: {str(e)}")
