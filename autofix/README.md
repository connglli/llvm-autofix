# llvm-autofix

Agentic tooling that fixes LLVM middle-end bugs. Two entry points:

- **`autofix.mini`** — the agent itself; run it locally against a single bug.
- **`autofix.ghbot`** — a GitHub App that wraps `mini` and runs it on
  `@llvm-autofix` mentions inside the
  [`dtcxzyw/llvm-autoreduce`](https://github.com/dtcxzyw/llvm-autoreduce)
  issue tracker.

## `autofix.mini`

Single-bug agent. Reproduces the bug, identifies the root cause, edits
LLVM source, and iterates until the reproducer passes and a curated set
of lit tests still pass.

### Inputs

A bug is specified in one of three ways (mutually exclusive):

| Flag | Source |
| --- | --- |
| `--issue <bench-id>` | Issue from the local `bench/` corpus. |
| `--reproducer <file.ll>` | Ad-hoc `.ll` file with embedded directives (see below). |
| `--issue <gh-id> --autoreduce` | GitHub issue ID in `dtcxzyw/llvm-autoreduce`; the issue body is fetched and normalized by the model into an ad-hoc reproducer, then handled as if `--reproducer` had been used. Implies `--pull-latest`. |

An ad-hoc reproducer file must embed two lit-style directives:

```llvm
; BUG: crash            ; or: miscompilation
; RUN: opt -passes=... %s
```

### Other flags

| Flag | Purpose |
| --- | --- |
| `--model <name>` | **Required.** LLM model name. |
| `--driver openai\|anthropic` | LLM driver (default `openai`). |
| `--base-commit <sha>` | Check out this LLVM commit before building. Overrides the bench-provided base. |
| `--pull-latest` | `git pull origin main` on the LLVM tree before building. Composes with `--base-commit` (pull first, then checkout). |
| `--aggressive-testing` | Validate patches against the entirety of `llvm/test/Transforms` and `llvm/test/Analysis` rather than the inferred subset. |
| `--interactive` | Expose the `ask` tool so the agent can prompt the user. |
| `--debug` | Verbose console output from the underlying agent. |
| `--stats <file>` | Write per-run statistics (rounds, tokens, wall time) as JSON. |

### Example

```shell
# A bench issue
python -m autofix.mini --issue 99899 --model gpt-5

# An ad-hoc reproducer
python -m autofix.mini --reproducer /tmp/crash.ll --model gpt-5 --driver openai

# Latest llvm-autoreduce issue, fetched and normalized via LLM
python -m autofix.mini --issue 1234 --autoreduce --model gpt-5
```

## `autofix.ghbot`

A GitHub App that turns the `mini` workflow into `@llvm-autofix` mentions
on `dtcxzyw/llvm-autoreduce` issues. Architecture: poll the issue
tracker, enqueue new mentions, drain the queue one at a time, post the
patch as a reply.

### User Permissions

Mentions are only honored when the commenter has `admin` or `write`
permission on the repository. Others are silently ignored.

For example:

```plain
@llvm-autofix please fix this bug!
```

### Bot Replies

For every mention from an authorized user the bot:

1. Reacts 👀 (`eyes`) on the mention as soon as it is picked up.
2. On success: posts a comment with the patch inline as a ```` ```diff ````
   block, the agent's patch report, and a collapsible `<details>` block
   with run stats; swaps 👀 → 🚀.
3. On failure: posts a comment with the error and traceback (collapsed);
   swaps 👀 → 👎.

The 👀 reaction also acts as a cross-process lock: a second `serve`
process that scans the same comment will see our reaction and skip it.

### Persistent queue

State lives in `~/.llvm-autofix-bot/queue.json`. Saves are atomic
(`tmp + os.replace`) so concurrent `queue --remove` and `serve` writers
do not corrupt it.

If a `serve` process is killed mid-job, entries left in `running` are
auto-reset to `pending` on the next startup, with an attempt counter;
after 3 attempts an entry is moved to `failed`.

### CLI

```shell
# Long-running poll loop
python -m autofix.ghbot serve --poll 60 --model gpt-5

# One tick (scan + drain), useful from cron
python -m autofix.ghbot serve --once --model gpt-5

# Inspect the on-disk queue
python -m autofix.ghbot queue --list

# Drop an entry by GitHub comment ID; also clears our 👀 reaction so
# the comment can be re-picked up by a later mention.
python -m autofix.ghbot queue --remove <comment-id>
```

`serve` accepts the same `--model` / `--driver` / `--debug` flags as
`mini`. `--poll` and `--once` are mutually exclusive.

### Configuration

| Env var | Purpose |
| --- | --- |
| `LLVM_AUTOFIX_GH_APP_ID` | GitHub App ID (numeric). |
| `LLVM_AUTOFIX_GH_PRIVATE_KEY_PATH` | Path to the App's `.pem` private key. |
| `LLVM_HARNESS_LM_*` | All LLM env vars consumed by the rest of the harness. |

Register the app at <https://github.com/settings/apps>, grant
**Issues: read & write** and **Metadata: read**, then install it on
`dtcxzyw/llvm-autoreduce`. Deployment knobs that are not env vars
(bot login, mention prefix, queue directory, retry cap, allowed
permission levels) live as module-level constants in
`autofix/ghbot_configs.py`; override programmatically by mutating the
attribute before importing `autofix.ghbot`.
