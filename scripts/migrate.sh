#!/usr/bin/env bash
set -euo pipefail
state_root=${1:?"Usage: migrate.sh STATE_ROOT"}
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
version_file="$state_root/.avatar-os-state-version"
current=0
[[ -f "$version_file" ]] && read -r current < "$version_file"
mkdir -p "$state_root/journal" "$state_root/tools"
[[ -e "$state_root/journal/events.jsonl" ]] || : > "$state_root/journal/events.jsonl"
cp "$repo_root/shared/avatar-os/tools/avatar_os.py" "$state_root/tools/avatar_os.py"
cp "$repo_root/shared/avatar-os/journal/README.md" "$state_root/journal/README.md"
if ((current < 1)); then
  printf '1\n' > "$version_file"
fi
mkdir -p "$state_root/registry"
cp -R "$repo_root/registry/." "$state_root/registry/"
python3 "$state_root/tools/avatar_os.py" --root "$state_root" --system "$state_root/registry/system.json" rebuild >/dev/null
echo "Avatar OS state schema: 1"
