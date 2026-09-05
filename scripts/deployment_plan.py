#!/usr/bin/env python3
"""Preview repository-to-Hermes deployment without changing either tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def tree_digest(path: Path) -> str | None:
    if not path.is_dir():
        return None
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def gateway_allowlist(config_path: Path) -> list[str]:
    if not config_path.is_file():
        return []
    result: list[str] = []
    in_list = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "multiplex_profile_allowlist:":
            in_list = True
            continue
        if in_list and line.startswith("    - "):
            result.append(line.removeprefix("    - ").strip())
        elif in_list and line.strip():
            break
    return result


def build_plan(system_path: Path, hermes_root: Path) -> dict[str, Any]:
    system = json.loads(system_path.read_text(encoding="utf-8"))
    agents = system["agents"]
    coordinator = next(str(agent["id"]) for agent in agents if agent.get("coordinator") is True)
    profiles = {}
    for agent in agents:
        agent_id = str(agent["id"])
        if (hermes_root / "profiles" / agent_id).is_dir():
            profiles[agent_id] = "keep"
        elif agent_id == coordinator and (hermes_root / "config.yaml").is_file() and (hermes_root / "SOUL.md").is_file():
            profiles[agent_id] = "keep-active"
        else:
            profiles[agent_id] = "install"
    state_root = hermes_root / coordinator
    source_registry = system_path.parent
    installed_registry = state_root / "registry"
    if not state_root.exists():
        state_action = "initialize"
    elif tree_digest(source_registry) != tree_digest(installed_registry):
        state_action = "migrate"
    else:
        state_action = "keep"
    allowlist = [str(agent["id"]) for agent in agents if not agent.get("coordinator", False)]
    installed_allowlist = gateway_allowlist(hermes_root / "config.yaml")
    return {
        "system": str(system_path),
        "hermes_root": str(hermes_root),
        "coordinator": coordinator,
        "profiles": profiles,
        "missing_profiles": [name for name, action in profiles.items() if action == "install"],
        "shared_state": state_action,
        "gateway_allowlist": allowlist,
        "installed_gateway_allowlist": installed_allowlist,
        "gateway": "keep" if installed_allowlist == allowlist else "update",
        "writes_live_state": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", type=Path, default=ROOT / "registry/system.json")
    parser.add_argument(
        "--hermes-root", type=Path,
        default=Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser(),
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        plan = build_plan(args.system.resolve(), args.hermes_root.resolve())
    except (OSError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        print(f"error: could not build deployment preview: {exc}")
        return 1
    if args.format == "json":
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    print("Avatar OS deployment preview (read-only)")
    for name, action in plan["profiles"].items():
        print(f"- profile {name}: {action}")
    print(f"- shared state: {plan['shared_state']}")
    print(f"- multiplex gateway: {plan['gateway']} ({', '.join(plan['gateway_allowlist']) or 'no specialists'})")
    print("No live files were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
