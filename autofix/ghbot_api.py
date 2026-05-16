"""GitHub-side helpers for the autofix bot.

* App authentication via :class:`github.GithubIntegration`.
* Mention parsing (``@llvm-autofix [args]``).
* Reaction add/remove for the 👀 / ✅ / ❌ status flow.
* Permission check (allow ``admin``/``write``).
* Markdown rendering for the result reply.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from github import Auth, Github, GithubException, GithubIntegration
from github.IssueComment import IssueComment
from github.Repository import Repository

from autofix import ghbot_configs
from autofix.autored import AUTOREDUCE_REPO

# Whole-body fullmatch: after stripping, the comment must be exactly
# ``@llvm-autofix`` (no instructions) or ``@llvm-autofix <whitespace> <rest>``.
# ``DOTALL`` lets multi-line instructions flow into the capture group.
_MENTION_RE = re.compile(
  rf"{re.escape(ghbot_configs.BOT_HANDLE)}(?:\s+(.*))?",
  re.DOTALL,
)

# GitHub reaction "content" values we care about.
REACTION_PICKED_UP = "eyes"  # 👀
REACTION_DONE = "rocket"  # 🚀  (no ✅/❌ in the API set; rocket/-1 are the closest)
REACTION_FAILED = "-1"  # 👎


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def make_installation_client() -> Tuple[Github, Repository]:
  """Authenticate as the GitHub App + return ``(client, autoreduce_repo)``.

  Reads ``LLVM_AUTOFIX_GH_APP_ID`` and ``LLVM_AUTOFIX_GH_PRIVATE_KEY_PATH``
  from env. Raises :class:`RuntimeError` with a setup hint if either is
  missing.
  """
  app_id = os.environ.get("LLVM_AUTOFIX_GH_APP_ID")
  pem_path = os.environ.get("LLVM_AUTOFIX_GH_PRIVATE_KEY_PATH")
  if not app_id or not pem_path:
    raise RuntimeError(
      "Set LLVM_AUTOFIX_GH_APP_ID and LLVM_AUTOFIX_GH_PRIVATE_KEY_PATH "
      "(path to the App's .pem). Register the app at "
      "https://github.com/settings/apps and install it on "
      f"{AUTOREDUCE_REPO}."
    )
  private_key = open(pem_path).read()
  integration = GithubIntegration(auth=Auth.AppAuth(int(app_id), private_key))
  owner, name = AUTOREDUCE_REPO.split("/", 1)
  installation = integration.get_repo_installation(owner, name)
  token = integration.get_access_token(installation.id).token
  gh = Github(auth=Auth.Token(token))
  return gh, gh.get_repo(AUTOREDUCE_REPO)


# ---------------------------------------------------------------------------
# Mention parsing
# ---------------------------------------------------------------------------


def parse_mention(body: Optional[str]) -> Optional[str]:
  """Return the instructions in a ``@llvm-autofix <instructions>`` comment.

  Strict: ``@llvm-autofix`` must be the very first token of the comment
  after stripping leading/trailing whitespace; everything after it (and a
  separating whitespace run) is returned as the instructions string,
  itself stripped. A bare ``@llvm-autofix`` with no trailing text returns
  ``""``. Anything that doesn't fit this shape — extra text before the
  handle, an inline mention, a typo'd handle — returns ``None``.
  """
  if not body:
    return None
  m = _MENTION_RE.fullmatch(body.strip())
  if not m:
    return None
  return (m.group(1) or "").strip()


# ---------------------------------------------------------------------------
# Permission gate
# ---------------------------------------------------------------------------


def is_authorized(repo: Repository, login: str) -> bool:
  """True iff *login* has ``write`` or ``admin`` permission on *repo*."""
  try:
    perm = repo.get_collaborator_permission(login)
  except GithubException:
    return False
  return perm in ghbot_configs.ALLOWED_PERMS


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------


def has_our_reaction(comment: IssueComment, kind: str, app_login: str) -> bool:
  """True iff *comment* already has a *kind* reaction from us.

  ``app_login`` is the bot user GitHub returns for the app (typically
  ``llvm-autofix[bot]``); compared against ``reaction.user.login``.
  """
  for r in comment.get_reactions():
    if r.content == kind and r.user and r.user.login == app_login:
      return True
  return False


def add_reaction(comment: IssueComment, kind: str) -> None:
  try:
    comment.create_reaction(kind)
  except GithubException:
    pass  # already exists — fine


def remove_our_reaction(comment: IssueComment, kind: str, app_login: str) -> None:
  for r in comment.get_reactions():
    if r.content == kind and r.user and r.user.login == app_login:
      try:
        r.delete()
      except GithubException:
        pass
      return


def swap_reaction(
  comment: IssueComment, *, remove: str, add: str, app_login: str
) -> None:
  remove_our_reaction(comment, remove, app_login)
  add_reaction(comment, add)


# ---------------------------------------------------------------------------
# Reply rendering
# ---------------------------------------------------------------------------

# Templates use ``str.format``; only ``{name}`` placeholders are interpreted, so
# diff/traceback content (which may contain literal ``{`` / ``}``) is safe to
# substitute. Optional sections are themselves rendered from sub-templates and
# spliced into the top-level template via ``{tail}``.

_SUCCESS_TEMPLATE = "@{requester} patch ready.\n\n```diff\n{patch}\n```{tail}"

_SUCCESS_REPORT_BLOCK = "\n\n{report}"

_SUCCESS_DETAILS_BLOCK = (
  "\n\n<details><summary>Run details</summary>\n\n{stats}\n\n</details>"
)

_FAILURE_TEMPLATE = "@{requester} autofix failed: `{error}`.{tail}"

_FAILURE_TRACEBACK_BLOCK = (
  "\n\n<details><summary>Traceback</summary>\n\n```\n{traceback}\n```\n</details>"
)


def render_success_reply(
  requester: str, patch: str, report: Optional[str], stats_lines: List[str]
) -> str:
  tail = ""
  if report:
    tail += _SUCCESS_REPORT_BLOCK.format(report=report.strip())
  if stats_lines:
    stats = "\n".join(f"- {line}" for line in stats_lines)
    tail += _SUCCESS_DETAILS_BLOCK.format(stats=stats)
  return _SUCCESS_TEMPLATE.format(requester=requester, patch=patch.rstrip(), tail=tail)


def render_failure_reply(
  requester: str, error: str, traceback: Optional[str] = None
) -> str:
  tail = ""
  if traceback:
    tail = _FAILURE_TRACEBACK_BLOCK.format(traceback=traceback.strip())
  return _FAILURE_TEMPLATE.format(requester=requester, error=error, tail=tail)
