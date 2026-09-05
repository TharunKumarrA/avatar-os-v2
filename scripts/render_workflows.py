#!/usr/bin/env python3
"""Compile registry workflows into Hermes cron files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render(root: Path, system_path: Path) -> dict[Path, str]:
    system = load_json(system_path)
    workflow_ref = Path(system.get("workflows", "workflows.json"))
    workflow_path = workflow_ref if workflow_ref.is_absolute() else system_path.parent / workflow_ref
    if not workflow_path.exists():
        workflow_path = root / "registry" / workflow_ref
    definitions = load_json(workflow_path)
    domains = []
    for reference in system["domains"]:
        path = Path(reference)
        manifest_path = path if path.is_absolute() else system_path.parent / path
        if not manifest_path.exists():
            manifest_path = root / "registry" / path
        domains.append(load_json(manifest_path))
    active = {agent["id"]: set(agent.get("domains", [])) for agent in system["agents"]}
    profiles = {agent["id"]: root / agent["profile"] for agent in system["agents"]}
    grouped: dict[str, list[dict]] = {}
    for workflow in definitions["workflows"]:
        profile = workflow["profile"]
        prompt = workflow["prompt"]
        if workflow.get("include_domain_close_prompts"):
            contributions = [
                domain["daily_close_prompt"] for domain in domains
                if domain["id"] in active[profile] and domain.get("daily_close_prompt")
            ]
            prompt += " Domain check-ins: " + "; ".join(contributions) + "."
        job_id = workflow.get("job_id", hashlib.sha256(workflow["id"].encode()).hexdigest()[:12])
        schedule = workflow["schedule"]
        skills = workflow["skills"]
        grouped.setdefault(profile, []).append({
            "id": job_id, "name": workflow["name"], "prompt": prompt,
            "skills": skills, "skill": skills[0], "model": workflow["model"],
            "provider": "openai-codex", "script": None, "no_agent": False,
            "schedule": {"kind": "cron", "expr": schedule, "display": schedule},
            "schedule_display": schedule, "repeat": {"times": None, "completed": 0},
            "enabled": True, "state": "scheduled", "deliver": "discord", "workdir": None,
        })
    return {profiles[name] / "cron/jobs.json": json.dumps({"jobs": jobs}, indent=2) + "\n" for name, jobs in grouped.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--system", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    system = args.system.resolve() if args.system else root / "registry/system.json"
    for target, content in render(root, system).items():
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                raise SystemExit(f"generated workflow drift: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
