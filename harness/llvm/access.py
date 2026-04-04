from fnmatch import fnmatch
from pathlib import Path

from harness.lms.tool import FuncToolCallException

# Absolute paths that are always readable and writable regardless of ACL config.
_ALWAYS_ALLOWED = ["/tmp"]


class AccessError(FuncToolCallException):
  """Raised when a path access check fails."""

  pass


class AccessControl:
  """Configurable file access policy for the LLVM workspace.

  Replaces hardcoded ``llvm/`` prefix checks with configurable glob
  patterns so that each harness scenario can specify exactly which
  paths are editable, readable, or ignored.

  Pattern matching uses :func:`fnmatch.fnmatch` (``*``, ``?``,
  ``[seq]``, ``[!seq]``).  A bare directory name without wildcard
  characters is treated as a prefix and matches everything underneath.

  Absolute paths under ``/tmp/`` are always allowed (readable and
  writable) to support temporary reproducer files.
  """

  def __init__(
    self,
    root: Path,
    *,
    editable: list[str] | None = None,
    readable: list[str] | None = None,
    ignored: list[str] | None = None,
  ):
    self.root = Path(root).resolve()
    self.editable = editable or ["llvm/lib", "llvm/include"]
    self.readable = readable or ["llvm"]
    self.ignored = ignored or []

  def _matches(self, path: str, patterns: list[str]) -> bool:
    for pat in patterns:
      if fnmatch(path, pat):
        return True
      # Bare directory prefix (no wildcard chars) matches anything underneath.
      if not any(c in pat for c in "*?[") and path.startswith(pat.rstrip("/") + "/"):
        return True
    return False

  def _is_always_allowed(self, path: str) -> bool:
    """Check if *path* is an absolute path under an always-allowed prefix."""
    resolved = str(Path(path).resolve())
    return any(resolved.startswith(p + "/") or resolved == p for p in _ALWAYS_ALLOWED)

  def _resolve(self, path: str) -> Path:
    # Absolute paths under always-allowed prefixes bypass the root check.
    if self._is_always_allowed(path):
      return Path(path).resolve()
    full = (self.root / path).resolve()
    if not full.is_relative_to(self.root):
      raise AccessError(
        f"Path escapes the workspace root: {path}. "
        "Please provide a relative path within the LLVM source tree."
      )
    return full

  def check_readable(self, path: str) -> Path:
    """Validate *path* is readable and return the resolved absolute path.

    Raises :class:`AccessError` if the path escapes the root, is not
    covered by any readable pattern, or matches an ignored pattern.
    Absolute paths under ``/tmp/`` are always readable.
    """
    full = self._resolve(path)
    if self._is_always_allowed(path):
      return full
    if not self._matches(path, self.readable):
      raise AccessError(
        f"Path is not readable: {path}. Readable paths: {', '.join(self.readable)}"
      )
    if self._matches(path, self.ignored):
      raise AccessError(
        f"Path is ignored: {path}. Ignored paths: {', '.join(self.ignored)}"
      )
    return full

  def check_editable(self, path: str) -> Path:
    """Validate *path* is editable and return the resolved absolute path.

    The path must also be readable (not ignored).
    Absolute paths under ``/tmp/`` are always editable.
    Raises :class:`AccessError` on violation.
    """
    full = self.check_readable(path)
    if self._is_always_allowed(path):
      return full
    if not self._matches(path, self.editable):
      raise AccessError(
        f"Path is not editable: {path}. Editable paths: {', '.join(self.editable)}"
      )
    return full

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

  def is_ignored(self, path: str) -> bool:
    """Return whether *path* matches any ignored pattern."""
    return self._matches(path, self.ignored)

  def describe(self) -> str:
    """Render access rules as human-readable text for prompt injection."""
    lines = [f"Editable paths: {', '.join(self.editable)}, /tmp"]
    lines.append(f"Readable paths: {', '.join(self.readable)}")
    if self.ignored:
      lines.append(f"Ignored paths: {', '.join(self.ignored)}")
    return "\n".join(lines)
