#!/usr/bin/env python3
"""Plan or create an Avatar OS Domain/Agent through the registry seam."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[a-z][a-z0-9-]*$")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def domain(root: Path, name: str, owner: str, apply: bool) -> list[str]:
    target = root / f"registry/domains/{name}.json"
    changes = [str(target.relative_to(root)), f"registry/system.json: assign {name} to {owner}"]
    if not apply:
        return changes
    system_path = root / "registry/system.json"
    system = json.loads(system_path.read_text())
    agent = next((item for item in system["agents"] if item["id"] == owner), None)
    if agent is None:
        raise SystemExit(f"unknown owner: {owner}")
    if target.exists() or f"domains/{name}.json" in system["domains"]:
        raise SystemExit(f"domain already exists: {name}")
    manifest = {
        "schema_version": 1, "id": name, "version": "1.0.0",
        "daily_close_prompt": f"{name.replace('-', ' ')} progress",
        "events": {f"{name}.update.v1": {
            "publishers": ["user", owner],
            "fields": {"note": {"type": "string", "max_length": 500}},
            "required": ["note"], "projections": [{"target": "daily", "operation": "merge", "namespace": name.replace('-', '_')}],
        }},
        "views": {"daily": [{"label": name.replace('-', ' ').title(), "path": f"{name.replace('-', '_')}.note"}], "weekly": [], "state": []},
    }
    write_json(target, manifest)
    system["domains"].append(f"domains/{name}.json")
    agent["domains"].append(name)
    write_json(system_path, system)
    return changes


def agent(root: Path, name: str, domains: list[str], apply: bool) -> list[str]:
    target = root / f"profiles/{name}"
    changes = [str(target.relative_to(root)), f"policy/roles/{name}.md", f"registry/system.json: add {name}"]
    if not apply:
        return changes
    system_path = root / "registry/system.json"
    system = json.loads(system_path.read_text())
    known = {Path(item).stem for item in system["domains"]}
    if target.exists() or any(item["id"] == name for item in system["agents"]):
        raise SystemExit(f"agent already exists: {name}")
    if not set(domains) <= known:
        raise SystemExit(f"unknown domains: {sorted(set(domains) - known)}")
    shutil.copytree(root / "profiles/toph", target)
    for generated in (target / "SOUL.md", target / "cron/jobs.json"):
        generated.unlink(missing_ok=True)
    old_skill = target / "skills/avatar-toph"
    new_skill = target / f"skills/avatar-{name}"
    if old_skill.exists():
        old_skill.rename(new_skill)
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".yaml", ".json"}:
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("Toph", name.title()).replace("toph", name), encoding="utf-8")
    policy = root / f"policy/roles/{name}.md"
    policy.write_text(f"## Role\n\nYou are {name.title()}, the specialist for: {', '.join(domains)}. Publish only registered events and use Avatar OS resources within your capabilities.\n", encoding="utf-8")
    system["agents"].append({
        "id": name, "profile": f"profiles/{name}", "policy": f"policy/roles/{name}.md",
        "env_path": f"profiles/{name}/.env", "coordinator": False, "domains": domains,
        "capabilities": ["events.publish", "resources.read.shared"],
        "toolsets": {"discord": ["avatar-os", "clarify", "memory", "skills", "todo", "vision"]},
    })
    write_json(system_path, system)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    subs = parser.add_subparsers(dest="kind", required=True)
    d = subs.add_parser("domain")
    d.add_argument("name"); d.add_argument("--owner", default="katara"); d.add_argument("--plan", action="store_true"); d.add_argument("--apply", action="store_true")
    a = subs.add_parser("agent")
    a.add_argument("name"); a.add_argument("--domains", nargs="+", required=True); a.add_argument("--plan", action="store_true"); a.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not ID.fullmatch(args.name):
        raise SystemExit("name must use lowercase letters, digits, and hyphens")
    apply = args.apply
    changes = domain(args.root.resolve(), args.name, args.owner, apply) if args.kind == "domain" else agent(args.root.resolve(), args.name, args.domains, apply)
    print(("Applied" if apply else "Plan") + ":")
    print("\n".join(f"- {item}" for item in changes))
    if not apply:
        print("Re-run with --apply to create it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
