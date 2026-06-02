# SLR-Engine Skill

A skill that turns any agent (Claude Code, Codex, Cursor, etc.) into a
review operator for SLR-Engine. The agent reads `SKILL.md` and follows
its operational rules — surfacing the disclaimer, walking the scoping
chain conversationally one step at a time, running scripts at the right
moments.

## Why this exists

Without the skill, agents tend to either (a) explain the engine instead
of running a review, or (b) dump the whole scoping form on the user at
once. The skill is explicit about doing neither.

## Installation

The skill format (markdown file with YAML frontmatter) is portable, but
each agent looks in different paths.

**Claude Code:** Copy or move `slr-engine/` to:
```
.claude/skills/slr-engine/SKILL.md
```
Either at the user level (`~/.claude/skills/`) or in the project root.

**Codex:** Copy or move `slr-engine/` to:
```
.codex/skills/slr-engine/SKILL.md
```

**Cursor / other agents:** Check that agent's docs for skill/agent-rule
paths. The `SKILL.md` content works for any agent that reads markdown
behavior files.

After installing, start a fresh agent session in the SLR-Engine repo root
and say: *"I want to do a literature review on [topic]."*
The agent should pick up the skill, surface the honesty disclaimer,
then walk the scoping conversation one step at a time.

## What's in `SKILL.md`

- **Frontmatter** — trigger phrases that invoke the skill
- **Mode detection** — fresh start, resume, or direct-stage
- **The scoping conversation** — explicit good/bad examples, hard rules
- **Pipeline operation** — when to run which script
- **Anti-patterns** — what NOT to do (forms, kit tours, repeated disclaimers)

## Maintenance

If SLR-Engine changes (new pipeline stage, new export artifact, etc.),
update `SKILL.md` to match. The skill is the operational source of truth
for running a review. Kit internals live in `docs/AGENT_GUIDE.md`.
Humans read [`README.md`](../README.md) at the repo root.
