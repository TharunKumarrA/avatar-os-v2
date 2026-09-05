#!/usr/bin/env python3
"""Validate installed Discord identity/channel settings without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[0-9]{15,22}$")


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if not path.is_file():
        raise ValueError(f"missing {path}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError(f"permissions on {path} must be 600")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def validate(root: Path, system_path: Path | None = None) -> list[str]:
    errors, tokens = [], []
    system_path = system_path or REPO_ROOT / "registry/system.json"
    try:
        agents = json.loads(system_path.read_text(encoding="utf-8"))["agents"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        return [f"could not load system registry: {exc}"]
    for agent in agents:
        role = str(agent["id"])
        env_path = root / str(agent["env_path"])
        try:
            values = read_env(env_path)
        except ValueError as exc:
            errors.append(str(exc)); continue
        token = values.get("DISCORD_BOT_TOKEN", "")
        if len(token) < 20:
            errors.append(f"{role}: DISCORD_BOT_TOKEN is missing or implausibly short")
        else:
            tokens.append(token)
        users = [item.strip() for item in values.get("DISCORD_ALLOWED_USERS", "").split(",") if item.strip()]
        if not users or any(not ID.fullmatch(item) for item in users):
            errors.append(f"{role}: DISCORD_ALLOWED_USERS must contain explicit numeric IDs")
        if not ID.fullmatch(values.get("DISCORD_HOME_CHANNEL", "")):
            errors.append(f"{role}: DISCORD_HOME_CHANNEL must be an explicit numeric ID")
    if len(tokens) != len(set(tokens)):
        errors.append("Discord bot tokens must be unique across profiles")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-root", type=Path, default=Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser())
    parser.add_argument("--system", type=Path, default=REPO_ROOT / "registry/system.json")
    args = parser.parse_args()
    errors = validate(args.hermes_root.resolve(), args.system.resolve())
    if errors:
        for error in errors: print(f"ERROR: {error}")
        return 1
    print("Runtime Discord identity and channel validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
