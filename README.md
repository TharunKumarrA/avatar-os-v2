# Avatar OS v2

Private, registry-driven Hermes/Discord personal operating system for Tharun.

This repository contains four independent Hermes profile distributions:

| Profile | Discord role | Primary channel |
| --- | --- | --- |
| Katara | Navigator and shared-context coordinator | `#avatar-hub`, `#service` |
| Toph | GATE CSE tutor | `#study` |
| Sokka | Health coach | `#health-metrics` |
| Iroh | Weekly reviewer | `#avatar-hub` |

The agents keep separate conversations. They coordinate through the authored
files under `shared/avatar-os/`: one canonical profile, Katara's shared live
context, daily/weekly records, and one structured handoff per specialist.

## Repository layout

```text
profiles/
  katara/                 official Hermes distribution
  toph/                   official Hermes distribution
  sokka/                  official Hermes distribution
  iroh/                   official Hermes distribution
shared/
  avatar-os/              shared source of truth and handoffs
  memory-seed/            optional curated memory seed, not session history
scripts/
  install.sh              preflighted, resumable transactional bootstrap
  migrate.sh              versioned shared-state migration
  restore.sh              restore a timestamped installer backup
  validate.py             repository and policy consistency checks
  validate_runtime.py     installed token/user/channel checks
  deployment_plan.py      read-only repository-to-Hermes change preview
  render_workflows.py     compile Domain-aware Hermes schedules
  scaffold.py             plan/create a Domain or Agent
  avatar_ops.py            inspect generations and atomically roll back
  audit-secrets.sh        pre-commit credential and path audit
registry/
  system.json             active agents and domain composition
  domains/                versioned event, projection, and view definitions
```

Hermes distributions represent one profile each, so this repository is a
monorepo of four valid distributions rather than pretending the stack is one
agent. The installer invokes the official `hermes profile install` command for
each profile.

## Extending the system

`registry/system.json` is the desired roster. A Domain manifest defines typed
Events, authorised publishers, deterministic projections, and rendered Views.
It can be assigned to one or more Agents without creating another bot. See
`registry/domains/reading.json` for the first extension beyond Fitness, GATE,
and DSA. It adds daily, weekly, state, and nightly-close behaviour without
changing runtime code.

Use the plan-first scaffolder rather than copying files by hand:

```bash
python3 scripts/scaffold.py domain language-learning --owner katara --plan
python3 scripts/scaffold.py domain language-learning --owner katara --apply
python3 scripts/scaffold.py agent bumi --domains gate --plan
```

Schedules live in `registry/workflows.json`. Domain manifests may contribute a
bounded `daily_close_prompt`; they cannot replace the workflow's safety,
identity, timing, or delivery instructions. Regenerate with
`python3 scripts/render_workflows.py`.

Adding an Agent is a separate choice: give it a Hermes profile and role policy,
then add it to the registry. Repository rendering, validation, installation,
restore, and runtime identity checks discover that roster automatically.

The Python layer does not replace or merge either CLI. Hermes still runs
profiles and Discord; Codex remains the development and administration tool.
Avatar OS sits between integrations and durable state as the small
`open`/`apply`/`handle` interface. `apply(..., mode="plan")` previews registry
changes. Commit mode validates existing events, writes an immutable generation,
and atomically activates it. No command edits a live `~/.hermes` installation
unless an operator explicitly runs the installer or migration script.

Before changing an installed system, run:

```bash
python3 scripts/deployment_plan.py
```

The preview recognizes both a named coordinator profile and Hermes' active
root-profile layout. It reports profile, shared-state, and multiplex-gateway
drift and never writes live files.

Inspect a live state directory or select a previously validated registry
generation with:

```bash
python3 scripts/avatar_ops.py --root ~/.hermes/katara status
python3 scripts/avatar_ops.py --root ~/.hermes/katara generations
python3 scripts/avatar_ops.py --root ~/.hermes/katara rollback GENERATION
```

Hermes receives the `avatar_os_record` tool through the standalone plugin in
`integrations/hermes/avatar-os`. The tool derives its Principal from Hermes'
active profile and never accepts a caller-supplied source or operational day.
The installer deploys and enables the plugin separately in every profile home
so multiplexed Discord sessions retain the correct identity.

The same plugin exposes `avatar_os_resource` for capability-scoped shared-state
access. Discord profiles do not receive Hermes' generic file tool: the Registry
declares each Agent's readable and writable paths and its allowed Discord
toolsets. CLI administration remains the trusted maintenance surface.

## Install on a clean machine

Prerequisites:

- Hermes Agent `>=0.20.6`
- Git and GitHub access to this private repository
- Four Discord bot tokens
- A ChatGPT/OpenAI Codex login for inference

Clone the repository and run:

```bash
./scripts/install.sh
```

To seed the curated user profile and durable memory into all four profiles:

```bash
./scripts/install.sh --with-memory
```

The installer refuses implicit overwrites. It installs Katara, Toph, Sokka, and
Iroh as named profiles, copies the shared source of truth to
`~/.hermes/katara`, and makes Katara the active profile. Use `--dry-run` for
preflight only, `--resume` after a partial installation, or `--repair` to back
up and reinstall distributions while preserving and migrating personal shared
state. Every mutating run stores recovery material under
`~/.hermes/backups/avatar-os/`; restore it with `scripts/restore.sh`.

After installation:

1. Copy each generated `.env.EXAMPLE` to `.env`.
2. Add the correct, unique `DISCORD_BOT_TOKEN` for that bot.
3. Set `DISCORD_ALLOWED_USERS` and `DISCORD_HOME_CHANNEL`.
4. Run `python3 scripts/validate_runtime.py`; it checks permissions, token
   uniqueness, and numeric user/channel IDs without printing secrets.
5. Authenticate the `openai-codex` provider with `hermes model` for each
   profile as needed.
6. Review the packaged cron jobs with `hermes -p katara cron list` and
   `hermes -p iroh cron list`; distribution installation does not execute them.
7. From the Katara profile, install/start the multiplex gateway.
8. Run `/reset` once for each Discord bot so its channel-bound skill loads into
   a fresh session.

The committed Discord channel IDs reproduce Tharun's existing server. Change
the `discord` sections in each `config.yaml` before starting the gateway if the
target server uses different channels.

## Scheduled jobs

- Katara Morning Brief — 09:00 Asia/Kolkata
- Katara Daily Close — 01:15 Asia/Kolkata
- Iroh Sunday Review — Sunday 19:00 Asia/Kolkata

The packaged jobs contain no execution history. Review them after installation;
Hermes computes their next run when the scheduler activates them.

## What is intentionally excluded

- Discord bot tokens and all `.env` files
- ChatGPT/OAuth credentials and `auth.json`
- Session transcripts and private conversation databases
- Runtime databases, logs, caches, checkpoints, and browser data
- Discord message history

`shared/memory-seed/` is an authored, reviewed memory seed. It is not a dump of
Hermes sessions or runtime memory databases.

## Security

Keep the GitHub repository private. Run this before every push:

```bash
./scripts/audit-secrets.sh
```

If a bot token or access token is ever committed, rotate it immediately; simply
deleting the file in a later commit does not remove it from Git history.
