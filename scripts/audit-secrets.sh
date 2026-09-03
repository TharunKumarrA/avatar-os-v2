#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
cd "$repo_root"

failed=false

forbidden=$(find . -type f \
  \( -name '.env' -o -name 'auth.json' -o -name 'auth.lock' \
     -o -name 'state.db' -o -name 'state.db-shm' -o -name 'state.db-wal' \
     -o -name '*.pem' -o -name '*.p12' \) -not -path './.git/*')
if [[ -n "$forbidden" ]]; then
  echo "Forbidden credential/runtime files found:" >&2
  echo "$forbidden" >&2
  failed=true
fi

patterns='(github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{20,}|DISCORD_BOT_TOKEN[[:space:]]*=[[:space:]]*[^[:space:]]+|Authorization:[[:space:]]*Bot[[:space:]]+[^[:space:]]+|/Users/[^/]+/\.hermes)'
if rg -n --hidden --glob '!.git/**' "$patterns" .; then
  echo "Potential secret or non-portable home path found." >&2
  failed=true
fi

if [[ "$failed" == true ]]; then
  exit 1
fi

echo "Secret audit passed."

