#!/usr/bin/env python3
"""Generate profile SOUL.md files from common and role policies."""

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument("--system", type=Path)
args = parser.parse_args()
root = args.root.resolve()
system_path = args.system.resolve() if args.system else root / "registry/system.json"
common = (root / "policy/common.md").read_text(encoding="utf-8").strip()
system = json.loads(system_path.read_text(encoding="utf-8"))

for agent in system["agents"]:
    role = str(agent["id"])
    specific = (root / agent["policy"]).read_text(encoding="utf-8").strip()
    content = f"# Avatar OS v2 — {agent.get('display_name', role.title())}\n\n{common}\n\n{specific}\n"
    target = root / agent["profile"] / "SOUL.md"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            try:
                display = target.relative_to(root)
            except ValueError:
                display = target
            raise SystemExit(f"generated profile drift: {display}")
    else:
        target.write_text(content, encoding="utf-8")
