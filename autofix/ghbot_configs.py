"""Programmatic configuration for the autofix GitHub bot.

Values that a deployer or test harness might want to override live here so
they can be tweaked by importing this module and mutating the attribute
before the rest of ``autofix.ghbot*`` is loaded — e.g.::

    from autofix import ghbot_configs
    ghbot_configs.STATE_DIR = tmp_path
    from autofix.ghbot import main
    main([...])

GitHub-API protocol values (reaction kinds, permission-API field names) stay
in their respective modules; only deployment knobs belong here.
"""

from __future__ import annotations

from pathlib import Path

# GitHub login the App posts and reacts as. Must match the installed App's
# slug (``<app-slug>[bot]``); update here if the App is renamed.
BOT_LOGIN = "llvm-autofix[bot]"

# Mention prefix the bot scans for in issue comments. The mention must own
# its own line — inline mentions are ignored.
BOT_HANDLE = "@llvm-autofix"

# Directory holding the persistent processing queue (``queue.json``).
STATE_DIR = Path.home() / ".llvm-autofix-bot"

# Cap on auto-retries for entries left in ``running`` across a ``serve``
# restart. Past this an entry is moved to ``failed`` instead of re-queued.
MAX_ATTEMPTS = 3

# Repo-collaborator permission levels allowed to invoke the bot. The values
# are GitHub's collaborator-permission names (``admin``/``write``/``read``/
# ``none``); anything not in this set is silently ignored.
ALLOWED_PERMS = frozenset({"admin", "write"})
