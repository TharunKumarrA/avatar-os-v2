# Avatar OS v2

Private, four-agent Hermes/Discord personal operating system for Tharun.

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
  audit-secrets.sh        pre-commit credential and path audit
```

Hermes distributions represent one profile each, so this repository is a
monorepo of four valid distributions rather than pretending the stack is one
agent. The installer invokes the official `hermes profile install` command for
each profile.

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
