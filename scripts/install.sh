#!/usr/bin/env bash
set -euo pipefail

with_memory=false
if [[ "${1:-}" == "--with-memory" ]]; then
  with_memory=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--with-memory]" >&2
  exit 2
fi

if ! command -v hermes >/dev/null 2>&1; then
  echo "Hermes is not installed or is not on PATH." >&2
  exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
hermes_root="$HOME/.hermes"
profiles_root="$hermes_root/profiles"

for profile in katara toph sokka iroh; do
  if [[ -e "$profiles_root/$profile" ]]; then
    echo "Refusing to overwrite existing profile: $profiles_root/$profile" >&2
    exit 1
  fi
done

if [[ -e "$hermes_root/katara" ]]; then
  echo "Refusing to overwrite existing shared data: $hermes_root/katara" >&2
  exit 1
fi

hermes profile install "$repo_root/profiles/katara" --name katara --alias --yes
hermes profile install "$repo_root/profiles/toph" --name toph --alias --yes
hermes profile install "$repo_root/profiles/sokka" --name sokka --alias --yes
hermes profile install "$repo_root/profiles/iroh" --name iroh --alias --yes

mkdir -p "$hermes_root/katara"
cp -R "$repo_root/shared/avatar-os/." "$hermes_root/katara/"

if [[ "$with_memory" == true ]]; then
  for profile in katara toph sokka iroh; do
    mkdir -p "$profiles_root/$profile/memories"
    cp "$repo_root/shared/memory-seed/USER.md" "$profiles_root/$profile/memories/USER.md"
    cp "$repo_root/shared/memory-seed/MEMORY.md" "$profiles_root/$profile/memories/MEMORY.md"
  done
fi

hermes profile use katara

cat <<'EOF'

Avatar OS v2 profiles are installed and Katara is active.

Next steps:
1. Configure each generated profile .env with that bot's unique Discord token.
2. Authenticate the openai-codex provider with `hermes model` as needed.
3. Review the committed Discord channel IDs in each config.yaml.
4. Review packaged jobs with `hermes -p katara cron list` and
   `hermes -p iroh cron list` before scheduling them.
5. Run `hermes gateway install`, then `hermes gateway start` from Katara.
6. Run /reset once for Katara, Toph, Sokka, and Iroh in Discord.
EOF
