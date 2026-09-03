#!/usr/bin/env bash
set -euo pipefail

minimum_hermes="0.20.6"
with_memory=false
mode="install"
dry_run=false

usage() { echo "Usage: $0 [--with-memory] [--dry-run] [--resume|--repair]" >&2; }
while (($#)); do
  case "$1" in
    --with-memory) with_memory=true ;;
    --dry-run) dry_run=true ;;
    --resume) mode="resume" ;;
    --repair) mode="repair" ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
  shift
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
hermes_root="${HERMES_HOME:-$HOME/.hermes}"
profiles_root="$hermes_root/profiles"
backup_root="$hermes_root/backups/avatar-os"
run_id=$(date +%Y%m%dT%H%M%S)
transaction="$backup_root/$run_id"
installed_this_run=()

version_ge() {
  python3 - "$1" "$2" <<'PY'
import re
import sys
parse = lambda value: tuple(int(part) for part in re.findall(r"\d+", value)[:3])
raise SystemExit(0 if parse(sys.argv[1]) >= parse(sys.argv[2]) else 1)
PY
}

preflight() {
  command -v hermes >/dev/null 2>&1 || { echo "Hermes is not installed or is not on PATH." >&2; return 1; }
  command -v python3 >/dev/null 2>&1 || { echo "python3 is required." >&2; return 1; }
  local version
  version=$(hermes --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)
  [[ -n "$version" ]] || { echo "Could not determine Hermes version." >&2; return 1; }
  version_ge "$version" "$minimum_hermes" || { echo "Hermes >= $minimum_hermes required; found $version." >&2; return 1; }
  command -v ruby >/dev/null 2>&1 || { echo "ruby is required for YAML validation." >&2; return 1; }
  python3 -m json.tool "$repo_root/profiles/katara/cron/jobs.json" >/dev/null
  python3 -m json.tool "$repo_root/profiles/iroh/cron/jobs.json" >/dev/null
  ruby -e 'require "yaml"; ARGV.each { |f| YAML.safe_load(File.read(f), permitted_classes: [], aliases: false) }' "$repo_root"/profiles/*/{config,distribution,profile}.yaml
  "$repo_root/scripts/audit-secrets.sh"
  python3 "$repo_root/scripts/validate.py"
}

rollback() {
  local status=$?
  ((status == 0)) && return
  echo "Install failed; restoring recoverable profile backups." >&2
  local profile
  set +u
  for profile in "${installed_this_run[@]}"; do
    if [[ -e "$profiles_root/$profile" ]]; then
      mkdir -p "$transaction/failed"
      mv "$profiles_root/$profile" "$transaction/failed/$profile"
    fi
    [[ -e "$transaction/profiles/$profile" ]] && mv "$transaction/profiles/$profile" "$profiles_root/$profile"
  done
  set -u
  echo "Recovery material: $transaction" >&2
  exit "$status"
}
preflight
trap rollback EXIT
existing=()
for profile in katara toph sokka iroh; do [[ -e "$profiles_root/$profile" ]] && existing+=("$profile"); done
[[ -e "$hermes_root/katara" ]] && existing+=("shared-state")
if [[ "$mode" == "install" && ${#existing[@]} -gt 0 ]]; then
  echo "Existing components: ${existing[*]}. Use --resume or --repair." >&2
  exit 1
fi

if [[ "$dry_run" == true ]]; then
  echo "Preflight passed. Mode=$mode Hermes root=$hermes_root"
  for profile in katara toph sokka iroh; do
    [[ -e "$profiles_root/$profile" ]] && action=keep || action=install
    [[ "$mode" == "repair" ]] && action=backup-and-reinstall
    echo "$profile: $action"
  done
  [[ -e "$hermes_root/katara" ]] && echo "shared state: preserve and migrate" || echo "shared state: initialize"
  trap - EXIT
  exit 0
fi

mkdir -p "$profiles_root" "$transaction"
for profile in katara toph sokka iroh; do
  if [[ -e "$profiles_root/$profile" ]]; then
    [[ "$mode" == "resume" ]] && { echo "Keeping existing profile: $profile"; continue; }
    mkdir -p "$transaction/profiles"
    mv "$profiles_root/$profile" "$transaction/profiles/$profile"
  fi
  installed_this_run+=("$profile")
  hermes profile install "$repo_root/profiles/$profile" --name "$profile" --alias --yes
done

if [[ ! -e "$hermes_root/katara" ]]; then
  mkdir -p "$hermes_root/katara"
  cp -R "$repo_root/shared/avatar-os/." "$hermes_root/katara/"
else
  mkdir -p "$transaction/katara-snapshot"
  cp -R "$hermes_root/katara/." "$transaction/katara-snapshot/"
  "$repo_root/scripts/migrate.sh" "$hermes_root/katara"
fi

if [[ "$with_memory" == true ]]; then
  for profile in katara toph sokka iroh; do
    mkdir -p "$profiles_root/$profile/memories"
    for file in USER.md MEMORY.md; do
      [[ -e "$profiles_root/$profile/memories/$file" && "$mode" != "repair" ]] || cp "$repo_root/shared/memory-seed/$file" "$profiles_root/$profile/memories/$file"
    done
  done
fi

hermes profile use katara
trap - EXIT
echo "Avatar OS v2 installation completed in $mode mode. Recovery backup: $transaction"
