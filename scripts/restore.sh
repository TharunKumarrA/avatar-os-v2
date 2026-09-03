#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 || ! -d "$1" ]]; then echo "Usage: $0 BACKUP_DIRECTORY" >&2; exit 2; fi
hermes_root="${HERMES_HOME:-$HOME/.hermes}"
backup=$(cd "$1" && pwd)
stamp=$(date +%Y%m%dT%H%M%S)
recovery="$hermes_root/backups/avatar-os/pre-restore-$stamp"
mkdir -p "$recovery/profiles"
for profile in katara toph sokka iroh; do
  if [[ -e "$backup/profiles/$profile" ]]; then
    [[ -e "$hermes_root/profiles/$profile" ]] && mv "$hermes_root/profiles/$profile" "$recovery/profiles/$profile"
    cp -R "$backup/profiles/$profile" "$hermes_root/profiles/$profile"
  fi
done
if [[ -e "$backup/katara-snapshot" ]]; then
  [[ -e "$hermes_root/katara" ]] && mv "$hermes_root/katara" "$recovery/katara"
  cp -R "$backup/katara-snapshot" "$hermes_root/katara"
elif [[ -e "$backup/katara" ]]; then
  [[ -e "$hermes_root/katara" ]] && mv "$hermes_root/katara" "$recovery/katara"
  cp -R "$backup/katara" "$hermes_root/katara"
fi
echo "Restore complete. Pre-restore state: $recovery"
