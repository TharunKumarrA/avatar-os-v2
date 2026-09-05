#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 || ! -d "$1" ]]; then echo "Usage: $0 BACKUP_DIRECTORY" >&2; exit 2; fi
hermes_root="${HERMES_HOME:-$HOME/.hermes}"
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
system_registry="${AVATAR_SYSTEM_REGISTRY:-$repo_root/registry/system.json}"
backup=$(cd "$1" && pwd)
stamp=$(date +%Y%m%dT%H%M%S)
recovery="$hermes_root/backups/avatar-os/pre-restore-$stamp"
mkdir -p "$recovery/profiles"
while IFS= read -r profile; do
  if [[ -e "$backup/profiles/$profile" ]]; then
    [[ -e "$hermes_root/profiles/$profile" ]] && mv "$hermes_root/profiles/$profile" "$recovery/profiles/$profile"
    cp -R "$backup/profiles/$profile" "$hermes_root/profiles/$profile"
  fi
done < <(python3 "$repo_root/scripts/registry.py" agents --system "$system_registry")
if [[ -e "$backup/katara-snapshot" ]]; then
  [[ -e "$hermes_root/katara" ]] && mv "$hermes_root/katara" "$recovery/katara"
  cp -R "$backup/katara-snapshot" "$hermes_root/katara"
elif [[ -e "$backup/katara" ]]; then
  [[ -e "$hermes_root/katara" ]] && mv "$hermes_root/katara" "$recovery/katara"
  cp -R "$backup/katara" "$hermes_root/katara"
fi
echo "Restore complete. Pre-restore state: $recovery"
