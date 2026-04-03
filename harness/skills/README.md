# Skills

Skills are domain specific capabilities exposed to the agent as reusable building blocks. Unlike tools (which execute code), a skill is a directory containing a `SKILL.md` file that defines a task the agent should perform, including its inputs and the tools it may use.

## Writing a Skill

Create a subdirectory under `harness/skills/` with a `SKILL.md` file:

```
harness/skills/
  my-skill/
    SKILL.md
    references/
    scripts/
```

`SKILL.md` consists of a YAML frontmatter block followed by a Markdown prompt body:

```markdown
---
name: my-skill
description: >
  One or two sentences describing what this skill does and when to invoke it.
context: fork
parameters:
  - name: my_param
    type: string
    required: true
    description: >
      Description of what this parameter contains and how it is used.
  - name: optional_param
    type: string
    required: false
    description: >
      An optional parameter. Leave empty if not applicable.
allowed-tools:
  - read
  - find
  - ripgrep
---

# Skill Title

Skill body goes here. Reference parameters using {{ my_param }} syntax.
```

## Naming Conventions

- Skill directory names use `kebab-case`.
- LLVM-specific skills use an `llvm-` prefix, e.g. `llvm-patchreview`, `llvm-bisect`.
- Generic skills (not tied to LLVM) use a plain descriptive name, e.g. `summarize`.

## Parameters

Parameters are declared in the frontmatter and injected into the skill body at invocation time using `{{ parameter_name }}` template placeholders. Each parameter has:

- `name`: identifier used in the template placeholder.
- `type`: the value type (`string` is the most common).
- `required`: whether the caller must supply a value.
- `description`: explains what the parameter contains and how the skill uses it.

### Parameter-free Skills

If a skill declares no parameters, a default optional `argument: str` parameter is added automatically. The skill's prompt body will receive a `# Arguments` section containing whatever the caller passed.

## Allowed Tools

The `allowed-tools` field lists the tool names the skill is permitted to call. Only tools registered with the agent at runtime are available regardless of what is listed here. If omitted, the skill has access to all tools registered with the agent.

## Context

The `context` field controls whether the skill shares the caller's conversation history:

- `context: fork` — the skill runs in isolation without access to the caller's prior messages. Use this for self-contained tasks that should not be influenced by earlier context.
- `context: inline` — the skill runs inline and shares the caller's full conversation history. Use this when the skill needs to refer to prior exchanges (e.g., a skill that summarizes or acts on what was discussed).

If omitted, the default behavior is `inline`.

## References

Skills can include a `references/` subdirectory containing files that the skill body can reference using `references/file.md`. This allows the agent to load additional information when needed. References will not be automatically included in the prompt; the skill must explicitly reference them in the skill body.

## Scripts

Skills can also include a `scripts/` subdirectory containing executable scripts that the skill can call using the `bash` tool. Like references, scripts are not automatically included in the prompt; the skill must explicitly call them using the `bash` tool with the appropriate path. Scripts used should be self-contained and executable. For any dependencies, the skill should mention how to install them in the skill body.

## Registering Skills

Skills are discovered automatically by `harness.skills.list_skills()`, which returns all subdirectories containing a `SKILL.md` file. No registration is required.
