#!/usr/bin/env python3
"""Query Avatar OS desired state for lifecycle scripts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    try:
        system = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load registry: {exc}") from exc
    agents = system.get("agents")
    if system.get("schema_version") != 1 or not isinstance(agents, list):
        raise ValueError("unsupported or invalid system registry")
    ids = [item.get("id") for item in agents if isinstance(item, dict)]
    if len(ids) != len(agents) or any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("agent ids must be present and unique")
    return system


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("agents", "specialists", "coordinator", "profiles", "env-paths"))
    parser.add_argument("--system", type=Path, default=ROOT / "registry/system.json")
    args = parser.parse_args()
    try:
        agents = load(args.system.resolve())["agents"]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.command == "agents":
        rows = [item["id"] for item in agents]
    elif args.command == "specialists":
        rows = [item["id"] for item in agents if not item.get("coordinator", False)]
    elif args.command == "coordinator":
        rows = [item["id"] for item in agents if item.get("coordinator", False)]
        if len(rows) != 1:
            print("error: registry must define exactly one coordinator", file=sys.stderr)
            return 1
    elif args.command == "profiles":
        rows = [f"{item['id']}\t{item['profile']}" for item in agents]
    else:
        rows = [f"{item['id']}\t{item['env_path']}" for item in agents]
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
