from fnmatch import fnmatch
from pathlib import Path

from harness.lms.tool import FuncToolCallException


class AccessError(FuncToolCallException):
  """Raised when a path access check fails."""

  pass


class AccessControl:
  """Pure file-access policy.

  Callers pass **absolute paths**; the policy answers yes/no based on
  configurable glob patterns.  Pattern matching uses
  :func:`fnmatch.fnmatch` (``*``, ``?``, ``[seq]``, ``[!seq]``).
  A bare directory name without wildcard characters is treated as a
  prefix and matches everything underneath.
  """

  def __init__(
    self,
    *,
    editable: list[str],
    readable: list[str],
    ignored: list[str] | None = None,
  ):
    self.editable = editable
    self.readable = readable
    self.ignored = ignored or []

  def _matches(self, path: str, patterns: list[str]) -> bool:
    for pat in patterns:
      if fnmatch(path, pat):
        return True
      # Bare directory prefix (no wildcard chars) matches anything underneath.
      if not any(c in pat for c in "*?[") and path.startswith(pat.rstrip("/") + "/"):
        return True
    return False

  def is_readable(self, path: str) -> bool:
    """Return whether *path* is readable according to the policy."""
    return self._matches(path, self.readable) and not self._matches(path, self.ignored)

  def is_editable(self, path: str) -> bool:
    """Return whether *path* is editable according to the policy."""
    return self.is_readable(path) and self._matches(path, self.editable)

  def is_ignored(self, path: str) -> bool:
    """Return whether *path* matches any ignored pattern."""
    return self._matches(path, self.ignored)

  def check_readable(self, path: str) -> Path:
    """Validate *path* is readable and return the resolved :class:`Path`.

    Raises :class:`AccessError` if the path is not covered by any
    readable pattern or matches an ignored pattern.
    """
    resolved = Path(path).resolve()
    rpath = str(resolved)
    if not self._matches(rpath, self.readable):
      raise AccessError(
        f"Path is not readable: {path}. Readable paths: {', '.join(self.readable)}"
      )
    if self._matches(rpath, self.ignored):
      raise AccessError(
        f"Path is ignored: {path}. Ignored paths: {', '.join(self.ignored)}"
      )
    return resolved

  def check_editable(self, path: str) -> Path:
    """Validate *path* is editable and return the resolved :class:`Path`.

    The path must also be readable (not ignored).
    Raises :class:`AccessError` on violation.
    """
    resolved = self.check_readable(path)
    rpath = str(resolved)
    if not self._matches(rpath, self.editable):
      raise AccessError(
        f"Path is not editable: {path}. Editable paths: {', '.join(self.editable)}"
      )
    return resolved

  def check_readable_file(self, path: str) -> Path:
    """Like :meth:`check_readable` but also asserts the path is an existing file."""
    full = self.check_readable(path)
    if not full.exists():
      raise AccessError(f"File does not exist: {path}")
    if not full.is_file():
      raise AccessError(f"Path is not a file: {path}")
    return full

  def check_readable_dir(self, path: str) -> Path:
    """Like :meth:`check_readable` but also asserts the path is an existing directory."""
    full = self.check_readable(path)
    if not full.exists():
      raise AccessError(f"Directory does not exist: {path}")
    if not full.is_dir():
      raise AccessError(f"Path is not a directory: {path}")
    return full

  def check_editable_file(self, path: str, *, should_exist: bool = True) -> Path:
    """Like :meth:`check_editable` but optionally asserts existence."""
    full = self.check_editable(path)
    if should_exist:
      if not full.exists():
        raise AccessError(f"File does not exist: {path}")
      if not full.is_file():
        raise AccessError(f"Path is not a file: {path}")
    return full

  def describe(self) -> str:
    """Render access rules as human-readable text for prompt injection."""
    lines = [f"Editable paths: {', '.join(self.editable)}"]
    lines.append(f"Readable paths: {', '.join(self.readable)}")
    if self.ignored:
      lines.append(f"Ignored paths: {', '.join(self.ignored)}")
    return "\n".join(lines)
