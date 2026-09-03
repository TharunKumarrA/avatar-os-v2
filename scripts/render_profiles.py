#!/usr/bin/env python3
"""Generate profile SOUL.md files from common and role policies."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = (ROOT / "policy/common.md").read_text(encoding="utf-8").strip()
parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()

for role in ("katara", "toph", "sokka", "iroh"):
    specific = (ROOT / "policy/roles" / f"{role}.md").read_text(encoding="utf-8").strip()
    content = f"# Avatar OS v2 — {role.title()}\n\n{COMMON}\n\n{specific}\n"
    target = ROOT / "profiles" / role / "SOUL.md"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            raise SystemExit(f"generated profile drift: {target.relative_to(ROOT)}")
    else:
        target.write_text(content, encoding="utf-8")
