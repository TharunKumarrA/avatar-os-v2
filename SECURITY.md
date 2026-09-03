# Security policy

This is a private personal-agent distribution containing personal routines,
goals, and authored memory seeds. Do not make the repository public without
removing or replacing `shared/` and reviewing every prompt.

Never commit:

- `.env`, Discord bot tokens, API keys, OAuth tokens, passwords, or cookies;
- `auth.json`, state databases, sessions, logs, caches, or browser profiles;
- exported Discord history or raw health records not intentionally authored for
  the shared context.

Run `scripts/audit-secrets.sh` before each commit and inspect `git diff --cached`
before pushing. If a secret reaches Git history, revoke/rotate it first, then
rewrite or remove the history as a separate cleanup step.

