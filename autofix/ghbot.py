"""autofix GitHub bot — runs autofix on ``@llvm-autofix`` mentions.

Two subcommands:

* ``serve --poll-interval N`` — long-running poll loop.
* ``serve --once``            — single tick (scan + drain), useful for cron.
* ``queue --list``            — show the current processing queue.
* ``queue --remove <id>``     — drop an entry by GitHub comment ID and clear
  the corresponding 👀 reaction so a re-mention can pick it up again.

Configuration (env):

* ``LLVM_AUTOFIX_GH_APP_ID``         — GitHub App ID (numeric).
* ``LLVM_AUTOFIX_GH_PRIVATE_KEY_PATH`` — path to the App's .pem file.
* All ``LLVM_HARNESS_LM_*`` env vars used by the rest of the harness.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from typing import List, Optional

# ---------------------------------------------------------------------------
# Environment-variable preflight
# ---------------------------------------------------------------------------
#
# We validate config up front so the user sees a clear "missing X, Y, Z"
# message instead of a KeyError from deep in the import chain or a 401 from
# GitHub after the first poll.

_GH_APP_ENV = ("LLVM_AUTOFIX_GH_APP_ID", "LLVM_AUTOFIX_GH_PRIVATE_KEY_PATH")

# Both the openai and anthropic drivers in harness/lms/ read this single var.
_LM_API_KEY_ENV = "LLVM_HARNESS_LM_API_KEY"

_ENV_HINTS = (
  "Hints:",
  "  * LAB_LLVM_*           — source ./buildscripts/upenv.sh",
  "  * LLVM_AUTOFIX_GH_*    — see autofix/README.md",
  "  * LLVM_HARNESS_LM_*    — set in the `environments` file (see project root)",
)


def _die_missing_env(missing: List[str]) -> None:
  lines = ["ghbot: missing required environment variable(s):"]
  lines += [f"  - {n}" for n in missing]
  lines += ["", *_ENV_HINTS]
  print("\n".join(lines), file=sys.stderr)
  raise SystemExit(2)


def _require_env(*names: str) -> None:
  """Exit 2 with a friendly listing if any of *names* is unset or empty."""
  missing = [n for n in names if not os.environ.get(n)]
  if missing:
    _die_missing_env(missing)


# Heavy imports below — some touch ``LAB_LLVM_*`` at module load time
# (e.g. ``harness.llvm.intern.llvm`` reads them with ``os.environ[...]``).
# Wrap so a missing harness var becomes the same shape of config-missing
# message as the ones we generate ourselves.
try:
  from autofix import ghbot_configs
  from autofix.autored import (
    AUTOREDUCE_REPO,
    ReprodInfo,
    fetch_autoreduce_reproducer,
  )
  from autofix.ghbot_api import (
    REACTION_DONE,
    REACTION_FAILED,
    REACTION_PICKED_UP,
    add_reaction,
    has_our_reaction,
    is_authorized,
    make_installation_client,
    parse_mention,
    remove_our_reaction,
    render_failure_reply,
    render_success_reply,
    swap_reaction,
  )
  from autofix.ghbot_queue import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Entry,
    Queue,
    utcnow_iso,
  )
  from autofix.mini import (
    ADDITIONAL_CMAKE_FLAGS,
    AGENT_MAX_CHAT_ROUNDS,
    AGENT_MAX_CONSUMED_TOKENS,
    NoAvailablePatchFound,
    RunStats,
    autofix,
    build_agent_config,
  )
  from harness.llvm import Harness
  from harness.lms.meter import GlobalMeter
except KeyError as _err:
  _var = _err.args[0] if _err.args else ""
  if isinstance(_var, str) and (
    _var.startswith("LAB_") or _var.startswith("LLM_HARNESS_LM_")
  ):
    _die_missing_env([_var])
  raise


# ---------------------------------------------------------------------------
# Scan: turn new GitHub comments into queue entries
# ---------------------------------------------------------------------------


def scan_and_enqueue(gh, repo, queue: Queue, *, log=print) -> int:
  """Pull comments since ``queue.last_poll`` and enqueue new mentions.

  Returns the number of new entries added. ``last_poll`` is updated to
  ``now`` regardless of how many entries were added.
  """
  scan_started = utcnow_iso()
  added = 0
  # PyGithub's get_issues_comments without `since` returns everything; only
  # pass since= when we have one.
  if queue.last_poll:
    from datetime import datetime, timezone

    since_dt = datetime.strptime(queue.last_poll, "%Y-%m-%dT%H:%M:%SZ").replace(
      tzinfo=timezone.utc
    )
    comments = repo.get_issues_comments(since=since_dt, sort="created")
  else:
    comments = repo.get_issues_comments(sort="created", direction="desc")
  for c in comments:
    if queue.has(c.id):
      continue
    instructions = parse_mention(c.body)
    if instructions is None:
      continue
    if c.user and c.user.login == ghbot_configs.BOT_LOGIN:
      continue  # our own replies/quotes
    # Atomic remote lock: if a 👀 from us is already there, the previous
    # run claimed this comment — skip until that entry resurfaces in state.
    if has_our_reaction(c, REACTION_PICKED_UP, ghbot_configs.BOT_LOGIN):
      continue
    if not c.user or not is_authorized(repo, c.user.login):
      log(f"skip {c.id}: {c.user and c.user.login} not authorized")
      continue
    issue_number = int(c.issue_url.rsplit("/", 1)[-1])
    entry = Entry(
      id=c.id,
      issue_number=issue_number,
      requester=c.user.login,
      instructions=instructions,
      status=STATUS_PENDING,
      claimed_at=utcnow_iso(),
    )
    queue.add(entry)
    add_reaction(c, REACTION_PICKED_UP)
    added += 1
    log(f"enqueued #{c.id} (issue {issue_number}, requester {c.user.login})")
  queue.last_poll = scan_started
  return added


# ---------------------------------------------------------------------------
# Drain: process one pending entry
# ---------------------------------------------------------------------------


def _run_autofix(entry: Entry, *, driver: str, model: str, debug: bool, log=print):
  """Run the full autoreduce → fix pipeline.

  Mirrors :func:`autofix.mini.main`: validate bug type, build the harness,
  explicitly reproduce the bug (so an un-reproducible issue surfaces as a
  clear error in the failure reply instead of a stack trace), run the
  agent, post-validate the patch against the full middle-end suite (since
  we run with ``aggressive_testing=False``), and pull token/round/wall-time
  stats from :class:`GlobalMeter` in ``finally`` so the run-details block
  in the reply is populated even on failure.
  """
  aconf = build_agent_config(driver, model, debug)
  GlobalMeter.configure(
    token_limit=AGENT_MAX_CONSUMED_TOKENS,
    round_limit=AGENT_MAX_CHAT_ROUNDS,
  )
  reproducer_path, rinfo = fetch_autoreduce_reproducer(
    str(entry.issue_number), agent_config=aconf
  )
  harness_ctx = Harness.from_reproducer(
    str(reproducer_path),
    base_commit=rinfo.llvm_commit,
    cmake_args=ADDITIONAL_CMAKE_FLAGS,
    aggressive_testing=False,
  )
  stats = RunStats(
    command={
      "via": "bot",
      "comment_id": entry.id,
      "issue": entry.issue_number,
      "requester": entry.requester,
      "instructions": entry.instructions,
      "model": model,
      "driver": driver,
    }
  )
  stats.total_time_sec = time.time()
  try:
    with harness_ctx as h:
      bug_type = h.fixenv.get_bug_type()
      if bug_type not in ("crash", "miscompilation"):
        raise RuntimeError(f"unsupported bug type {bug_type!r}")

      log(f"building LLVM @ {rinfo.llvm_commit[:12]} and reproducing ...")
      try:
        rep = h.reproduce()
      except Exception as e:
        raise RuntimeError(
          f"could not reproduce on LLVM @ {rinfo.llvm_commit[:12]}: {e}"
        ) from e
      log("reproduced; handing off to agent")

      try:
        stats.patch = autofix(rep=rep, harness=h, aconf=aconf, stats=stats)
      except Exception as e:
        raise RuntimeError(f"agent failed running: {e}") from e

      log("agent finished; validating patch ...")
      if not stats.patch:
        raise NoAvailablePatchFound("agent finished without producing a patch")

      if not h.fixenv.use_entire_regression_test_suite:
        log("post-validating patch against the full middle-end suite ...")
        passed, errmsg = h.post_validate()
        if not passed:
          stats.patch = None
          raise NoAvailablePatchFound(f"post-validation failed: {errmsg}")
  finally:
    gm = GlobalMeter.instance()
    stats.chat_rounds = gm.total_rounds
    stats.input_tokens = gm.total_input_tokens
    stats.output_tokens = gm.total_output_tokens
    stats.cached_tokens = gm.total_cached_tokens
    stats.total_tokens = gm.total_tokens
    stats.total_time_sec = time.time() - stats.total_time_sec
  return stats, rinfo


def _stats_lines(stats: RunStats, rinfo: ReprodInfo) -> List[str]:
  return [
    f"LLVM commit: `{rinfo.llvm_commit}`",
    f"chat rounds: {stats.chat_rounds}",
    f"tokens: input={stats.input_tokens}, output={stats.output_tokens}, "
    f"cached={stats.cached_tokens}",
    f"wall time: {stats.total_time_sec:.1f}s",
  ]


def drain_one(
  gh, repo, queue: Queue, *, driver: str, model: str, debug: bool, log=print
) -> Optional[Entry]:
  """Process the oldest pending entry, if any. Returns the processed entry
  or ``None`` when the queue has no pending work."""
  pending = queue.pending()
  if not pending:
    return None
  entry = pending[0]
  queue.mark_running(entry)
  queue.save()  # crash safety: writing 'running' first ensures auto-retry can recover
  comment = repo.get_issue(entry.issue_number).get_comment(entry.id)
  log(f"processing #{entry.id} (issue {entry.issue_number}, attempt {entry.attempts})")
  try:
    stats, rinfo = _run_autofix(entry, driver=driver, model=model, debug=debug, log=log)
    reply_body = render_success_reply(
      entry.requester, stats.patch, stats.patch_report, _stats_lines(stats, rinfo)
    )
    posted = repo.get_issue(entry.issue_number).create_comment(reply_body)
    swap_reaction(
      comment,
      remove=REACTION_PICKED_UP,
      add=REACTION_DONE,
      app_login=ghbot_configs.BOT_LOGIN,
    )
    queue.mark_done(entry, posted.id)
    log(f"done #{entry.id} → reply {posted.id}")
  except Exception as e:
    err = f"{type(e).__name__}: {e}"
    tb = traceback.format_exc()
    log(f"failed #{entry.id}: {err}")
    try:
      posted = repo.get_issue(entry.issue_number).create_comment(
        render_failure_reply(entry.requester, err, tb)
      )
      result_id = posted.id
    except Exception as post_err:
      log(f"  also failed to post reply: {post_err}")
      result_id = None
    swap_reaction(
      comment,
      remove=REACTION_PICKED_UP,
      add=REACTION_FAILED,
      app_login=ghbot_configs.BOT_LOGIN,
    )
    queue.mark_failed(entry, err)
    entry.result_comment_id = result_id
  finally:
    queue.save()
  return entry


# ---------------------------------------------------------------------------
# Tick: scan + drain
# ---------------------------------------------------------------------------


def tick(gh, repo, queue: Queue, *, driver: str, model: str, debug: bool, log=print):
  added = scan_and_enqueue(gh, repo, queue, log=log)
  queue.save()
  if added == 0 and not queue.pending():
    log("no new mentions, queue empty")
  while drain_one(gh, repo, queue, driver=driver, model=model, debug=debug, log=log):
    pass


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_serve(args) -> int:
  _require_env(*_GH_APP_ENV, _LM_API_KEY_ENV)
  queue = Queue.load()
  recovered = queue.recover_stale_running()
  if recovered:
    print(f"recovered {len(recovered)} stale running entr(ies); see `queue --list`")
    queue.save()
  gh, repo = make_installation_client()
  if args.once:
    tick(
      gh,
      repo,
      queue,
      driver=args.driver,
      model=args.model,
      debug=args.debug,
    )
    return 0
  while True:
    try:
      tick(
        gh,
        repo,
        queue,
        driver=args.driver,
        model=args.model,
        debug=args.debug,
      )
    except KeyboardInterrupt:
      print("interrupted; saving queue")
      queue.save()
      return 130
    except Exception as e:
      print(f"tick raised {type(e).__name__}: {e} — backing off")
    time.sleep(args.poll_interval)


def _batch_remove(queue: Queue, ids: List[int]) -> List[Entry]:
  """Best-effort batch removal — skip missing or running entries with a
  printed warning, return the list of entries actually removed.

  Caller is responsible for ``queue.save()`` and for clearing the 👀
  reactions on GitHub for the returned entries.
  """
  removed: List[Entry] = []
  for cid in ids:
    entry = queue.find(cid)
    if entry is None:
      print(f"skip {cid}: not in queue")
      continue
    try:
      queue.remove(cid)
    except RuntimeError as e:
      print(f"skip {cid}: {e}")
      continue
    removed.append(entry)
  return removed


def _clear_reactions(removed: List[Entry], *, log=print) -> None:
  """Clear our 👀 reaction on each removed entry's mention so a future
  re-mention can re-pick it up. Best-effort — a failure here doesn't undo
  the local removal."""
  if not removed:
    return
  _require_env(*_GH_APP_ENV)
  try:
    gh, repo = make_installation_client()
  except Exception as e:
    log(f"removed locally; could not authenticate to clear reactions: {e}")
    return
  for entry in removed:
    try:
      comment = repo.get_issue(entry.issue_number).get_comment(entry.id)
      remove_our_reaction(comment, REACTION_PICKED_UP, ghbot_configs.BOT_LOGIN)
    except Exception as e:
      log(f"removed #{entry.id} locally; could not clear reaction on GitHub: {e}")


def _ids_to_remove(args, queue: Queue) -> List[int]:
  """Translate the chosen `queue --remove*` flag into a list of comment IDs.

  Status-keyed flags only return entries with a matching status; ``running``
  entries are always excluded since :meth:`Queue.remove` refuses them
  anyway (and a `--remove-all` that wipes an in-flight job would corrupt
  the serve loop's view of the world).
  """
  if args.remove is not None:
    return list(args.remove)
  if args.remove_all:
    return [e.id for e in queue.entries if e.status != STATUS_RUNNING]
  for flag, status in (
    ("remove_pending", STATUS_PENDING),
    ("remove_done", STATUS_DONE),
    ("remove_failed", STATUS_FAILED),
  ):
    if getattr(args, flag):
      return [e.id for e in queue.entries if e.status == status]
  return []


def cmd_queue(args) -> int:
  queue = Queue.load()
  if args.list:
    print(queue.render_table())
    return 0
  ids = _ids_to_remove(args, queue)
  if not ids:
    print("no matching entries to remove")
    return 0
  removed = _batch_remove(queue, ids)
  if removed:
    queue.save()
  _clear_reactions(removed)
  print(f"removed {len(removed)} entr{'y' if len(removed) == 1 else 'ies'}")
  return 0 if removed else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
  parser = argparse.ArgumentParser(
    description=(
      f"GitHub bot that runs autofix on `{ghbot_configs.BOT_HANDLE}` mentions in "
      f"{AUTOREDUCE_REPO} issues."
    ),
  )
  sub = parser.add_subparsers(dest="cmd", required=True)

  s = sub.add_parser("serve", help="Run the polling/processing loop.")
  mode = s.add_mutually_exclusive_group(required=True)
  mode.add_argument(
    "--poll",
    type=int,
    default=None,
    dest="poll_interval",
    help="Loop forever, sleeping this many seconds between ticks.",
  )
  mode.add_argument(
    "--once",
    action="store_true",
    default=False,
    help="Run one tick (scan + drain) and exit. Useful from cron.",
  )
  s.add_argument(
    "--model",
    required=True,
    help="LLM model name used for both autoreduce parsing and the fix run.",
  )
  s.add_argument(
    "--driver",
    default="openai",
    choices=["openai", "anthropic"],
    help="LLM API driver (default: openai).",
  )
  s.add_argument(
    "--debug",
    action="store_true",
    default=False,
    help="Verbose console output from the underlying agent.",
  )
  s.set_defaults(func=cmd_serve)

  q = sub.add_parser("queue", help="Inspect or edit the on-disk queue.")
  qmode = q.add_mutually_exclusive_group(required=True)
  qmode.add_argument(
    "--list",
    action="store_true",
    default=False,
    help="List all queue entries.",
  )
  qmode.add_argument(
    "--remove",
    type=int,
    nargs="+",
    metavar="COMMENT_ID",
    default=None,
    help="Remove one or more entries by GitHub comment ID.",
  )
  qmode.add_argument(
    "--remove-all",
    action="store_true",
    default=False,
    help="Remove every entry that isn't currently running.",
  )
  qmode.add_argument(
    "--remove-pending",
    action="store_true",
    default=False,
    help="Remove every pending entry (mention enqueued but not yet processed).",
  )
  qmode.add_argument(
    "--remove-done",
    action="store_true",
    default=False,
    help="Remove every successfully processed entry.",
  )
  qmode.add_argument(
    "--remove-failed",
    action="store_true",
    default=False,
    help="Remove every failed entry (errored or hit the attempt cap).",
  )
  q.set_defaults(func=cmd_queue)

  args = parser.parse_args(argv)
  return args.func(args)


if __name__ == "__main__":
  raise SystemExit(main())
