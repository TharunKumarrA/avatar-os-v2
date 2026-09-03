#!/usr/bin/env python3
"""Mechanical reliability layer for Avatar OS.

The JSONL journal is authoritative. Reconciliation creates an immutable
snapshot and atomically moves the ``journal/current`` symlink to it.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

VERSION = 1
ZONE = ZoneInfo("Asia/Kolkata")
CUTOFF = dt.time(1, 30)
SOURCES = {"user", "katara", "toph", "sokka", "iroh", "automation"}
SOURCE_TYPES = {
    "user": {"daily_log", "decision", "effort_score"},
    "katara": {"daily_log", "decision", "state_update", "effort_score"},
    "toph": {"gate_log", "gate_next"},
    "sokka": {"health_log", "readiness"},
    "iroh": {"review_proposal"},
    "automation": {"run_result"},
}
TYPE_FIELDS = {
    "daily_log": {"gate_minutes", "gate_topic", "gym", "dsa", "fruit", "protein_hits", "sleep", "wake", "energy", "stress", "soreness", "deviation", "friction", "win"},
    "gate_log": {"gate_minutes", "gate_topic", "questions", "correct", "weakness", "next_action"},
    "gate_next": {"next_action"},
    "health_log": {"gym", "fruit", "protein_hits", "sleep", "wake", "energy", "stress", "soreness", "illness", "deviation"},
    "readiness": {"readiness", "constraint", "next_action"},
    "decision": {"proposal_id", "decision", "note"},
    "state_update": {"mode", "next_gate", "next_fitness", "next_dsa"},
    "review_proposal": {"proposal_id", "proposal", "evidence", "status"},
    "effort_score": {"logging_seconds", "reconciliation_delay_minutes", "corrections", "prompt_responded", "reduced_effort_score"},
    "run_result": {"job", "scheduled_at", "actual_at", "target_operational_day", "target_week", "input_checkpoint", "status", "files_updated", "delivery_status", "error"},
}
REQUIRED_FIELDS = {
    "review_proposal": {"proposal_id", "proposal"},
    "decision": {"proposal_id", "decision"},
    "run_result": {"job", "status"},
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class JournalError(ValueError):
    pass


def root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JournalError(f"invalid occurred_at: {value}") from exc
    if parsed.tzinfo is None:
        raise JournalError("occurred_at must include a UTC offset")
    return parsed


def operational_day(when: dt.datetime) -> str:
    local = when.astimezone(ZONE)
    day = local.date() - dt.timedelta(days=1) if local.time() < CUTOFF else local.date()
    return day.isoformat()


def _safe_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def validate_event(raw: dict[str, Any]) -> dict[str, Any]:
    required = {"event_id", "source", "occurred_at", "operational_day", "type", "payload"}
    if set(raw) - (required | {"schema_version"}):
        raise JournalError(f"unknown event keys: {sorted(set(raw) - required - {'schema_version'})}")
    if not required.issubset(raw):
        raise JournalError(f"missing event keys: {sorted(required - set(raw))}")
    if raw.get("schema_version", VERSION) != VERSION:
        raise JournalError("unsupported schema_version")
    event_id = raw["event_id"]
    if not isinstance(event_id, str) or not ID_RE.fullmatch(event_id):
        raise JournalError("invalid event_id")
    source, kind = raw["source"], raw["type"]
    if source not in SOURCES or kind not in SOURCE_TYPES[source]:
        raise JournalError(f"source {source!r} cannot publish {kind!r}")
    occurred = parse_time(raw["occurred_at"])
    try:
        dt.date.fromisoformat(raw["operational_day"])
    except (TypeError, ValueError) as exc:
        raise JournalError("operational_day must be YYYY-MM-DD") from exc
    payload = raw["payload"]
    if not isinstance(payload, dict) or not payload:
        raise JournalError("payload must be a non-empty object")
    unknown = set(payload) - TYPE_FIELDS[kind]
    if unknown:
        raise JournalError(f"fields not allowed for {kind}: {sorted(unknown)}")
    if not all(_safe_scalar(value) for value in payload.values()):
        raise JournalError("payload values must be scalar")
    missing_payload = REQUIRED_FIELDS.get(kind, set()) - set(payload)
    if missing_payload:
        raise JournalError(f"missing fields for {kind}: {sorted(missing_payload)}")
    for key, value in payload.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise JournalError(f"{key} must be finite")
        if key in {"gate_minutes", "questions", "correct", "protein_hits", "logging_seconds", "reconciliation_delay_minutes", "corrections"} and isinstance(value, (int, float)) and value < 0:
            raise JournalError(f"{key} cannot be negative")
        if key in {"energy", "stress", "reduced_effort_score"} and isinstance(value, (int, float)) and not 1 <= value <= 10:
            raise JournalError(f"{key} must be between 1 and 10")
    clean = dict(raw)
    clean["schema_version"] = VERSION
    clean["occurred_at"] = occurred.isoformat()
    return clean


@contextlib.contextmanager
def locked(root: Path) -> Iterator[None]:
    journal = root / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    lock_path = journal / ".reconcile.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _canonical(event: dict[str, Any]) -> bytes:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def append_event(root: Path, event: dict[str, Any]) -> bool:
    event = validate_event(event)
    path = root / "journal" / "events.jsonl"
    with locked(root):
        existing = {item["event_id"]: item for item in read_events(path)}
        prior = existing.get(event["event_id"])
        if prior:
            if _canonical(prior) != _canonical(event):
                raise JournalError(f"event_id collision: {event['event_id']}")
            return False
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, _canonical(event))
            os.fsync(fd)
        finally:
            os.close(fd)
    return True


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JournalError(f"invalid JSON at line {line_no}") from exc
            try:
                events.append(validate_event(raw))
            except JournalError as exc:
                raise JournalError(f"line {line_no}: {exc}") from exc
    return events


def deduplicate(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, bytes] = {}
    unique = []
    for event in events:
        encoded = _canonical(event)
        prior = seen.get(event["event_id"])
        if prior and prior != encoded:
            raise JournalError(f"event_id collision: {event['event_id']}")
        if not prior:
            seen[event["event_id"]] = encoded
            unique.append(event)
    return sorted(unique, key=lambda item: (parse_time(item["occurred_at"]), item["event_id"]))


def project(events: list[dict[str, Any]]) -> dict[str, Any]:
    daily: dict[str, dict[str, Any]] = defaultdict(dict)
    proposals: dict[str, dict[str, Any]] = {}
    runs = []
    state: dict[str, Any] = {}
    for event in events:
        kind, payload, day = event["type"], event["payload"], event["operational_day"]
        if kind in {"daily_log", "gate_log", "health_log", "readiness", "effort_score"}:
            daily[day].update(payload)
        elif kind == "review_proposal":
            proposals[str(payload["proposal_id"])] = dict(payload)
        elif kind == "decision":
            proposal_id = str(payload["proposal_id"])
            proposals.setdefault(proposal_id, {"proposal_id": proposal_id}).update(payload)
        elif kind == "run_result":
            runs.append({"occurred_at": event["occurred_at"], **payload})
        elif kind == "state_update":
            state.update(payload)
        elif kind in {"gate_next", "readiness"}:
            state.update(payload)
    return {"schema_version": VERSION, "daily": dict(sorted(daily.items())), "state": state, "proposals": proposals, "runs": runs}


def _display(value: Any) -> str:
    if value is None:
        return "Not logged"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:500] or "Not logged"


def daily_markdown(day: str, values: dict[str, Any]) -> str:
    labels = [
        ("GATE", "gate_minutes"), ("GATE topic", "gate_topic"), ("Gym", "gym"),
        ("DSA", "dsa"), ("Fruit", "fruit"), ("Protein hits", "protein_hits"),
        ("Sleep", "sleep"), ("Wake", "wake"), ("Energy (1–10)", "energy"),
        ("Stress (1–10)", "stress"), ("Soreness/pain/illness", "soreness"),
        ("Readiness", "readiness"), ("Deviations", "deviation"),
    ]
    lines = [f"# AVATAR DAILY — {day}", "", "Generated from the event journal. Do not edit directly.", "", "## Log", ""]
    lines.extend(f"- {label}: {_display(values.get(key))}" for label, key in labels)
    lines.extend(["", "## Close", "", f"- One win: {_display(values.get('win'))}", f"- Friction: {_display(values.get('friction'))}", ""])
    return "\n".join(lines)


def usefulness_markdown(projection: dict[str, Any]) -> str:
    daily = projection["daily"]
    measured = [row for row in daily.values() if any(key in row for key in TYPE_FIELDS["effort_score"])]
    def median(key: str) -> str:
        values = sorted(float(row[key]) for row in measured if isinstance(row.get(key), (int, float)))
        if not values:
            return "Not logged"
        middle = len(values) // 2
        value = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        return f"{value:g}"
    responses = [row.get("prompt_responded") for row in measured if isinstance(row.get("prompt_responded"), bool)]
    rate = "Not logged" if not responses else f"{sum(responses) / len(responses):.0%}"
    corrections = sum(int(row.get("corrections", 0)) for row in measured if isinstance(row.get("corrections", 0), (int, float)))
    runs = projection["runs"]
    cron_rate = "Not logged" if not runs else f"{sum(run.get('status') == 'success' for run in runs) / len(runs):.0%}"
    proposals = list(projection["proposals"].values())
    decided = [proposal for proposal in proposals if proposal.get("decision") in {"accept", "modify", "reject"}]
    acceptance = "Not logged" if not decided else f"{sum(proposal.get('decision') == 'accept' for proposal in decided) / len(decided):.0%}"
    return "\n".join(["# Avatar OS usefulness", "", "Generated from effort_score, run_result, and decision events. Review after four weeks and simplify rituals that cost more effort than they save.", "", f"- Days measured: {len(measured)}", f"- Median logging time (seconds): {median('logging_seconds')}", f"- Median reconciliation delay (minutes): {median('reconciliation_delay_minutes')}", f"- Nightly prompt response rate: {rate}", f"- Corrections: {corrections}", f"- Cron success rate: {cron_rate}", f"- Weekly proposal acceptance: {acceptance}", f"- Median reduced-effort score: {median('reduced_effort_score')}", ""])


def weekly_markdown(week: str, rows: list[dict[str, Any]]) -> str:
    numeric = lambda key: sum(float(row.get(key, 0)) for row in rows if isinstance(row.get(key), (int, float)))
    yes = lambda key: sum(str(row.get(key, "")).lower() in {"yes", "done", "completed", "a", "b"} for row in rows)
    return "\n".join([f"# AVATAR WEEK — {week}", "", "Generated from the event journal. Do not edit directly.", "", "## Actuals", "", f"- GATE minutes: {numeric('gate_minutes'):g}", f"- Gym sessions: {yes('gym')}", f"- DSA days: {yes('dsa')}", f"- Fruit days: {yes('fruit')}", f"- Protein hits: {numeric('protein_hits'):g}", ""])


def state_markdown(state: dict[str, Any]) -> str:
    return "\n".join(["# AVATAR STATE", "", "Generated from the event journal. Do not edit directly.", "", f"- Mode: {_display(state.get('mode'))}", f"- NEXT GATE: {_display(state.get('next_gate', state.get('next_action')))}", f"- NEXT FITNESS: {_display(state.get('next_fitness', state.get('constraint')))}", f"- NEXT DSA: {_display(state.get('next_dsa'))}", f"- Readiness: {_display(state.get('readiness'))}", ""])


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
    with path.open(mode, **kwargs) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def reconcile(root: Path) -> Path:
    with locked(root):
        journal = root / "journal"
        events_path = journal / "events.jsonl"
        raw_bytes = events_path.read_bytes() if events_path.exists() else b""
        events = deduplicate(read_events(events_path))
        projection = project(events)
        checkpoint = {
            "schema_version": VERSION,
            "processed_through": hashlib.sha256(raw_bytes).hexdigest(),
            "processed_event_ids": [event["event_id"] for event in events],
            "event_count": len(events),
        }
        snapshots = journal / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".pending-", dir=snapshots))
        _write(stage / "projection.json", json.dumps(projection, indent=2, sort_keys=True) + "\n")
        _write(stage / "checkpoint.json", json.dumps(checkpoint, indent=2, sort_keys=True) + "\n")
        for day, values in projection["daily"].items():
            _write(stage / "daily" / f"{day}.md", daily_markdown(day, values))
        weeks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for day, values in projection["daily"].items():
            date = dt.date.fromisoformat(day)
            week = (date - dt.timedelta(days=date.weekday())).isoformat()
            weeks[week].append(values)
        for week, rows in weeks.items():
            _write(stage / "weekly" / f"{week}.md", weekly_markdown(week, rows))
        _write(stage / "STATE.md", state_markdown(projection["state"]))
        _write(stage / "SHARED_CONTEXT.md", state_markdown(projection["state"]).replace("# AVATAR STATE", "# SHARED CONTEXT", 1))
        _write(stage / "USEFULNESS.md", usefulness_markdown(projection))
        snapshot = snapshots / f"snapshot-{uuid.uuid4().hex}"
        os.replace(stage, snapshot)
        temp_link = journal / f".current-{uuid.uuid4().hex}"
        temp_link.symlink_to(snapshot.relative_to(journal))
        os.replace(temp_link, journal / "current")
        return snapshot


def backup(root: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"avatar-os-{dt.datetime.now(ZONE).strftime('%Y%m%dT%H%M%S%z')}"
    shutil.copytree(root, target, symlinks=True, ignore=shutil.ignore_patterns(".reconcile.lock", ".pending-*"))
    return target


def restore(source: Path, destination: Path) -> None:
    if not (source / "AGENT_CONTRACTS.md").is_file():
        raise JournalError("backup does not look like Avatar OS state")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent))
    shutil.rmtree(stage)
    shutil.copytree(source, stage, symlinks=True)
    if destination.exists():
        old = destination.with_name(f"{destination.name}.pre-restore-{uuid.uuid4().hex[:8]}")
        os.replace(destination, old)
    os.replace(stage, destination)


def make_event(args: argparse.Namespace) -> dict[str, Any]:
    occurred = parse_time(args.occurred_at) if args.occurred_at else dt.datetime.now(ZONE)
    payload = json.loads(args.payload)
    return {
        "schema_version": VERSION,
        "event_id": args.event_id or f"evt-{uuid.uuid4()}",
        "source": args.source,
        "occurred_at": occurred.isoformat(),
        "operational_day": args.operational_day or operational_day(occurred),
        "type": args.type,
        "payload": payload,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--root", type=Path, default=root_from_script())
    subs = result.add_subparsers(dest="command", required=True)
    add = subs.add_parser("append")
    add.add_argument("--source", required=True, choices=sorted(SOURCES))
    add.add_argument("--type", required=True)
    add.add_argument("--payload", required=True, help="JSON object")
    add.add_argument("--event-id")
    add.add_argument("--occurred-at")
    add.add_argument("--operational-day")
    subs.add_parser("reconcile")
    subs.add_parser("rebuild")
    op = subs.add_parser("operational-day")
    op.add_argument("timestamp", nargs="?")
    save = subs.add_parser("backup")
    save.add_argument("destination", type=Path)
    load = subs.add_parser("restore")
    load.add_argument("source", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "append":
            created = append_event(root, make_event(args))
            print("appended" if created else "duplicate ignored")
        elif args.command in {"reconcile", "rebuild"}:
            print(reconcile(root))
        elif args.command == "operational-day":
            when = parse_time(args.timestamp) if args.timestamp else dt.datetime.now(ZONE)
            print(operational_day(when))
        elif args.command == "backup":
            print(backup(root, args.destination.resolve()))
        elif args.command == "restore":
            restore(args.source.resolve(), root)
            print(root)
    except (JournalError, json.JSONDecodeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
