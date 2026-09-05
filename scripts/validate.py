#!/usr/bin/env python3
"""Repository consistency and policy checks without third-party packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PATH = Path(os.environ.get("AVATAR_SYSTEM_REGISTRY", ROOT / "registry/system.json")).resolve()
SYSTEM = json.loads(SYSTEM_PATH.read_text(encoding="utf-8"))
AGENTS = SYSTEM["agents"]
FORBIDDEN_DISCORD = {"terminal", "code_execution", "computer_use", "cronjob", "delegation", "image_gen", "browser", "web", "session_search"}
errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yaml_list_under(text: str, section: str, key: str) -> list[str]:
    lines = text.splitlines()
    section_index = lines.index(f"{section}:")
    key_index = next(index for index in range(section_index + 1, len(lines)) if lines[index] == f"  {key}:")
    result = []
    for line in lines[key_index + 1:]:
        if line.startswith("    - "):
            result.append(line.removeprefix("    - ").strip())
        elif line.strip():
            break
    return result


for agent in AGENTS:
    role = str(agent["id"])
    base = ROOT / agent["profile"]
    for name in ("SOUL.md", "config.yaml", "distribution.yaml", "profile.yaml"):
        if not (base / name).is_file():
            fail(f"missing {base / name}")
    config = (base / "config.yaml").read_text(encoding="utf-8")
    if "    - avatar-os" not in config:
        fail(f"{role}: authenticated Avatar OS toolset is not enabled")
    expected_discord = agent.get("toolsets", {}).get("discord", [])
    if yaml_list_under(config, "platform_toolsets", "discord") != expected_discord:
        fail(f"{role}: Discord toolsets drift from registry")
    if "hard_stop_enabled: true" not in config or "max_turns: 30" not in config:
        fail(f"{role}: loop hard stops are not enforced")
    match = re.search(r"^platform_toolsets:\n.*?^  discord:\n(?P<body>.*?)(?=^  google_chat:)", config, re.M | re.S)
    if not match:
        fail(f"{role}: missing Discord toolset")
    else:
        tools = set(re.findall(r"^    - ([\w-]+)$", match.group("body"), re.M))
        forbidden = tools & FORBIDDEN_DISCORD
        if forbidden:
            fail(f"{role}: forbidden Discord tools: {sorted(forbidden)}")
    discord = re.search(r"^discord:\n(?P<body>.*)\Z", config, re.M | re.S)
    if not discord or not re.search(r"^  allowed_channels: .+", discord.group("body"), re.M):
        fail(f"{role}: allowed_channels must be explicit")
    distro = (base / "distribution.yaml").read_text(encoding="utf-8")
    for env_name in ("DISCORD_BOT_TOKEN", "DISCORD_ALLOWED_USERS", "DISCORD_HOME_CHANNEL"):
        if env_name not in distro:
            fail(f"{role}: distribution does not require {env_name}")

mirrors = SYSTEM.get("skill_mirrors", [])
for left, right in mirrors:
    if digest(ROOT / left) != digest(ROOT / right):
        fail(f"duplicated skill drift: {left} != {right}")

subprocess.run([sys.executable, str(ROOT / "scripts/render_profiles.py"), "--check", "--system", str(SYSTEM_PATH)], check=True)
subprocess.run([sys.executable, str(ROOT / "scripts/render_workflows.py"), "--check", "--system", str(SYSTEM_PATH)], check=True)
for path in (ROOT / "integrations/hermes/avatar-os/plugin.yaml", ROOT / "integrations/hermes/avatar-os/__init__.py"):
    if not path.is_file():
        fail(f"missing Hermes adapter file: {path}")
for agent in AGENTS:
    role = str(agent["id"])
    soul = ROOT / agent["profile"] / "SOUL.md"
    if "Avatar OS v2" not in soul.read_text(encoding="utf-8"):
        fail(f"{role}: stale product version in SOUL.md")

for path in ROOT.rglob("*.json"):
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON {path.relative_to(ROOT)}: {exc}")

for path in ROOT.rglob("*.md"):
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", text):
        clean = target.split("#", 1)[0]
        if not clean or "://" in clean or clean.startswith(("mailto:", "/")):
            continue
        if not (path.parent / clean).resolve().exists():
            fail(f"broken reference in {path.relative_to(ROOT)}: {target}")

template = (ROOT / "shared/avatar-os/DAILY_TEMPLATE.md").read_text(encoding="utf-8")
if re.search(r"^- GATE: 0m$|^- DSA: No$", template, re.M):
    fail("daily template treats unknown as failure")
close = next(job for job in json.loads((ROOT / "profiles/katara/cron/jobs.json").read_text(encoding="utf-8"))["jobs"] if job["name"] == "Katara Daily Close")["prompt"]
if "TARGET_OPERATIONAL_DAY" not in close or "01:30" not in close or "today's" in close.lower():
    fail("nightly close does not use an exact operational day")

if errors:
    print("\n".join(f"ERROR: {item}" for item in errors), file=sys.stderr)
    raise SystemExit(1)
print("Avatar OS validation passed")
