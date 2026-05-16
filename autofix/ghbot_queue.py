"""Persistent processing queue for the autofix GitHub bot.

A single JSON file at :data:`ghbot_configs.STATE_DIR` ``/queue.json`` holds:

* ``last_poll`` — ISO-8601 timestamp; the ``serve`` loop uses it as the
  ``since`` argument when listing new issue comments.
* ``entries`` — every comment we've ever picked up, with status tracking.

Saves are atomic via ``tmp + os.replace`` so the CLI's ``queue --remove``
and the ``serve`` loop don't corrupt each other in mid-write.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from autofix import ghbot_configs

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_FAILED})


def utcnow_iso() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Entry:
  id: int  # GitHub issue-comment ID — primary key
  issue_number: int
  requester: str
  instructions: str  # free-form text after ``@llvm-autofix`` in the mention
  status: str  # pending | running | done | failed
  claimed_at: str
  attempts: int = 0
  started_at: Optional[str] = None
  finished_at: Optional[str] = None
  result_comment_id: Optional[int] = None
  error: Optional[str] = None


class Queue:
  """In-memory view of the on-disk queue. Call :meth:`save` to persist."""

  def __init__(self, last_poll: Optional[str], entries: List[Entry]):
    self.last_poll = last_poll
    self.entries = entries

  # --------------------------- I/O ---------------------------

  @classmethod
  def path(cls) -> Path:
    return ghbot_configs.STATE_DIR / "queue.json"

  @classmethod
  def load(cls) -> "Queue":
    p = cls.path()
    if not p.exists():
      return cls(last_poll=None, entries=[])
    data = json.loads(p.read_text())
    return cls(
      last_poll=data.get("last_poll"),
      entries=[Entry(**e) for e in data.get("entries", [])],
    )

  def save(self) -> None:
    p = self.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
      "last_poll": self.last_poll,
      "entries": [asdict(e) for e in self.entries],
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, p)

  # ------------------------ Mutations ------------------------

  def find(self, comment_id: int) -> Optional[Entry]:
    for e in self.entries:
      if e.id == comment_id:
        return e
    return None

  def has(self, comment_id: int) -> bool:
    return self.find(comment_id) is not None

  def add(self, entry: Entry) -> None:
    if self.has(entry.id):
      raise ValueError(f"entry {entry.id} already in queue")
    self.entries.append(entry)

  def remove(self, comment_id: int) -> Entry:
    entry = self.find(comment_id)
    if entry is None:
      raise KeyError(f"no queue entry with id {comment_id}")
    if entry.status == STATUS_RUNNING:
      raise RuntimeError(f"entry {comment_id} is currently running; refuse to remove")
    self.entries.remove(entry)
    return entry

  # ------------------------ Iteration ------------------------

  def pending(self) -> List[Entry]:
    """Pending entries in insertion order (FIFO)."""
    return [e for e in self.entries if e.status == STATUS_PENDING]

  def running(self) -> List[Entry]:
    return [e for e in self.entries if e.status == STATUS_RUNNING]

  # ------------------ Status transitions ---------------------

  def mark_running(self, entry: Entry) -> None:
    entry.status = STATUS_RUNNING
    entry.started_at = utcnow_iso()
    entry.attempts += 1

  def mark_done(self, entry: Entry, result_comment_id: Optional[int]) -> None:
    entry.status = STATUS_DONE
    entry.finished_at = utcnow_iso()
    entry.result_comment_id = result_comment_id
    entry.error = None

  def mark_failed(self, entry: Entry, error: str) -> None:
    entry.status = STATUS_FAILED
    entry.finished_at = utcnow_iso()
    entry.error = error

  def recover_stale_running(self) -> List[Entry]:
    """Reset entries left in ``running`` (process died mid-job) for retry.

    Bumps ``attempts`` and resets the entry to ``pending`` unless we've
    exceeded :data:`ghbot_configs.MAX_ATTEMPTS` — in which case it becomes
    ``failed``. Returns the entries that were touched (for logging).
    """
    touched: List[Entry] = []
    max_attempts = ghbot_configs.MAX_ATTEMPTS
    for e in self.running():
      if e.attempts >= max_attempts:
        e.status = STATUS_FAILED
        e.finished_at = utcnow_iso()
        e.error = f"exceeded {max_attempts} attempts (auto-retry give-up)"
      else:
        e.status = STATUS_PENDING
        e.started_at = None
      touched.append(e)
    return touched

  # ------------------------ Display --------------------------

  def render_table(self) -> str:
    if not self.entries:
      return "(queue empty)"
    rows = [("COMMENT_ID", "ISSUE", "STATUS", "REQUESTER", "ATTEMPTS", "AGE", "ERROR")]
    now = datetime.now(timezone.utc)
    for e in self.entries:
      rows.append(
        (
          str(e.id),
          str(e.issue_number),
          e.status,
          e.requester,
          str(e.attempts),
          _age(e.claimed_at, now),
          (e.error or "-")[:60],
        )
      )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for r in rows:
      lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(lines)


def _age(iso: str, now: datetime) -> str:
  try:
    when = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
  except Exception:
    return "?"
  delta = now - when
  s = int(delta.total_seconds())
  if s < 60:
    return f"{s}s"
  if s < 3600:
    return f"{s // 60}m"
  if s < 86400:
    return f"{s // 3600}h"
  return f"{s // 86400}d"
