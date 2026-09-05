#!/usr/bin/env python3
"""Inspect and recover an Avatar OS state directory."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path


def current_name(root: Path) -> str | None:
    current = root / "registry/current"
    return current.resolve().name if current.is_symlink() else None


def status(root: Path) -> dict:
    events = root / "journal/events.jsonl"
    count = sum(1 for line in events.read_text(encoding="utf-8").splitlines() if line.strip()) if events.exists() else 0
    snapshots = root / "journal/snapshots"
    latest = (root / "journal/current").resolve().name if (root / "journal/current").is_symlink() else None
    generations = root / "registry/generations"
    return {
        "event_count": count, "current_snapshot": latest, "current_generation": current_name(root),
        "generation_count": len([p for p in generations.iterdir() if p.is_dir()]) if generations.exists() else 0,
        "snapshot_count": len([p for p in snapshots.iterdir() if p.is_dir() and not p.name.startswith('.')]) if snapshots.exists() else 0,
    }


def rollback(root: Path, generation: str) -> None:
    registry = root / "registry"
    target = registry / "generations" / generation
    if not target.is_dir() or not (target / "lock.json").is_file():
        raise SystemExit(f"unknown or incomplete generation: {generation}")
    current = registry / "current"
    link = registry / f".rollback-{uuid.uuid4().hex}"
    link.symlink_to(target.relative_to(registry))
    os.replace(link, current)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("status")
    subs.add_parser("generations")
    rb = subs.add_parser("rollback"); rb.add_argument("generation")
    args = parser.parse_args(); root = args.root.resolve()
    if args.command == "status":
        print(json.dumps(status(root), indent=2))
    elif args.command == "generations":
        base = root / "registry/generations"
        print("\n".join(sorted((p.name for p in base.iterdir() if p.is_dir()), reverse=True)) if base.exists() else "")
    else:
        rollback(root, args.generation); print(f"Current registry generation: {args.generation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
