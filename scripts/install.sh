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
system_registry="${AVATAR_SYSTEM_REGISTRY:-$repo_root/registry/system.json}"
hermes_root="${HERMES_HOME:-$HOME/.hermes}"
profiles_root="$hermes_root/profiles"
backup_root="$hermes_root/backups/avatar-os"
run_id=$(date +%Y%m%dT%H%M%S)
transaction="$backup_root/$run_id"
installed_this_run=()
adapter_root_changed=false
adapter_profiles_changed=()
profiles=()
profile_paths=()
coordinator=""

load_registry() {
  while IFS=$'\t' read -r profile profile_path; do
    profiles+=("$profile")
    profile_paths+=("$profile_path")
  done < <(python3 "$repo_root/scripts/registry.py" profiles --system "$system_registry")
  coordinator=$(python3 "$repo_root/scripts/registry.py" coordinator --system "$system_registry")
}

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
  if [[ "$adapter_root_changed" == true ]]; then
    rm -rf "$hermes_root/plugins/avatar-os"
    [[ -e "$transaction/plugins/avatar-os" ]] && mv "$transaction/plugins/avatar-os" "$hermes_root/plugins/avatar-os"
  fi
  for profile in "${adapter_profiles_changed[@]}"; do
    rm -rf "$profiles_root/$profile/plugins/avatar-os"
    if [[ -e "$transaction/profile-plugins/$profile/avatar-os" ]]; then
      mkdir -p "$profiles_root/$profile/plugins"
      mv "$transaction/profile-plugins/$profile/avatar-os" "$profiles_root/$profile/plugins/avatar-os"
    fi
  done
  set -u
  echo "Recovery material: $transaction" >&2
  exit "$status"
}
preflight
load_registry
trap rollback EXIT
existing=()
for profile in "${profiles[@]}"; do [[ -e "$profiles_root/$profile" ]] && existing+=("$profile"); done
[[ -e "$hermes_root/katara" ]] && existing+=("shared-state")
if [[ "$mode" == "install" && ${#existing[@]} -gt 0 ]]; then
  echo "Existing components: ${existing[*]}. Use --resume or --repair." >&2
  exit 1
fi

if [[ "$dry_run" == true ]]; then
  echo "Preflight passed. Mode=$mode Hermes root=$hermes_root"
  for profile in "${profiles[@]}"; do
    [[ -e "$profiles_root/$profile" ]] && action=keep || action=install
    [[ "$mode" == "repair" ]] && action=backup-and-reinstall
    echo "$profile: $action"
  done
  [[ -e "$hermes_root/katara" ]] && echo "shared state: preserve and migrate" || echo "shared state: initialize"
  trap - EXIT
  exit 0
fi

mkdir -p "$profiles_root" "$transaction"
for index in "${!profiles[@]}"; do
  profile=${profiles[$index]}
  profile_source=${profile_paths[$index]}
  [[ "$profile_source" = /* ]] || profile_source="$repo_root/$profile_source"
  if [[ -e "$profiles_root/$profile" ]]; then
    [[ "$mode" == "resume" ]] && { echo "Keeping existing profile: $profile"; continue; }
    mkdir -p "$transaction/profiles"
    mv "$profiles_root/$profile" "$transaction/profiles/$profile"
  fi
  installed_this_run+=("$profile")
  hermes profile install "$profile_source" --name "$profile" --alias --yes
  if [[ -f "$transaction/profiles/$profile/.env" ]]; then
    cp "$transaction/profiles/$profile/.env" "$profiles_root/$profile/.env"
    chmod 600 "$profiles_root/$profile/.env"
  fi
done

adapter_source="$repo_root/integrations/hermes/avatar-os"
if [[ -e "$hermes_root/plugins/avatar-os" ]]; then
  mkdir -p "$transaction/plugins"
  mv "$hermes_root/plugins/avatar-os" "$transaction/plugins/avatar-os"
fi
adapter_root_changed=true
mkdir -p "$hermes_root/plugins"
cp -R "$adapter_source" "$hermes_root/plugins/avatar-os"
hermes plugins enable avatar-os --no-allow-tool-override
for profile in "${profiles[@]}"; do
  mkdir -p "$profiles_root/$profile/plugins"
  if [[ -e "$profiles_root/$profile/plugins/avatar-os" ]]; then
    mkdir -p "$transaction/profile-plugins/$profile"
    mv "$profiles_root/$profile/plugins/avatar-os" "$transaction/profile-plugins/$profile/avatar-os"
  fi
  adapter_profiles_changed+=("$profile")
  cp -R "$adapter_source" "$profiles_root/$profile/plugins/avatar-os"
  hermes -p "$profile" plugins enable avatar-os --no-allow-tool-override
done

if [[ ! -e "$hermes_root/katara" ]]; then
  mkdir -p "$hermes_root/katara"
  cp -R "$repo_root/shared/avatar-os/." "$hermes_root/katara/"
  mkdir -p "$hermes_root/katara/registry"
  cp -R "$repo_root/registry/." "$hermes_root/katara/registry/"
else
  mkdir -p "$transaction/katara-snapshot"
  cp -R "$hermes_root/katara/." "$transaction/katara-snapshot/"
  "$repo_root/scripts/migrate.sh" "$hermes_root/katara"
fi

if [[ "$with_memory" == true ]]; then
  for profile in "${profiles[@]}"; do
    mkdir -p "$profiles_root/$profile/memories"
    for file in USER.md MEMORY.md; do
      [[ -e "$profiles_root/$profile/memories/$file" && "$mode" != "repair" ]] || cp "$repo_root/shared/memory-seed/$file" "$profiles_root/$profile/memories/$file"
    done
  done
fi

hermes profile use "$coordinator"
trap - EXIT
echo "Avatar OS v2 installation completed in $mode mode. Recovery backup: $transaction"
