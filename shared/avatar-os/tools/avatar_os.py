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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
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


@dataclass(frozen=True)
class CompiledRegistry:
    principals: frozenset[str]
    capabilities: Mapping[str, frozenset[str]]
    resources: Mapping[str, Mapping[str, tuple[str, ...]]]
    events: Mapping[str, Mapping[str, Any]]
    daily_views: tuple[Mapping[str, Any], ...]
    weekly_views: tuple[Mapping[str, Any], ...]
    state_views: tuple[Mapping[str, Any], ...]
    domains: Mapping[str, Mapping[str, Any]]


def _validate_domain_manifest(manifest: Mapping[str, Any], reference: str, principals: frozenset[str]) -> None:
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("id"), str):
        raise JournalError(f"invalid domain manifest: {reference}")
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", str(manifest["id"])):
        raise JournalError(f"invalid domain id: {manifest['id']}")
    if not isinstance(manifest.get("version"), str) or not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest["version"])):
        raise JournalError(f"invalid domain version: {reference}")
    events = manifest.get("events")
    if not isinstance(events, dict) or not events:
        raise JournalError(f"domain must define events: {reference}")
    allowed_types = {"string", "integer", "number", "boolean"}
    allowed_projections = {
        ("daily", "merge"), ("state", "merge"),
        ("proposals", "upsert"), ("proposals", "merge"),
        ("runs", "append"),
    }
    for event_type, definition in events.items():
        if not isinstance(event_type, str) or not isinstance(definition, dict):
            raise JournalError(f"invalid event definition in {reference}")
        publishers = definition.get("publishers")
        if not isinstance(publishers, list) or not publishers or not set(publishers) <= principals:
            raise JournalError(f"invalid publishers for {event_type}")
        fields = definition.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise JournalError(f"invalid fields for {event_type}")
        for name, rule in fields.items():
            field_types = rule.get("type") if isinstance(rule, dict) else None
            field_types = field_types if isinstance(field_types, list) else [field_types]
            if not isinstance(name, str) or not field_types or not set(field_types) <= allowed_types:
                raise JournalError(f"invalid field rule for {event_type}.{name}")
        required = definition.get("required", [])
        if not isinstance(required, list) or not set(required) <= set(fields):
            raise JournalError(f"invalid required fields for {event_type}")
        projections = definition.get("projections")
        if not isinstance(projections, list) or not projections:
            raise JournalError(f"invalid projections for {event_type}")
        for projection in projections:
            if not isinstance(projection, dict) or (projection.get("target"), projection.get("operation")) not in allowed_projections:
                raise JournalError(f"invalid projection for {event_type}")
            rename = projection.get("rename", {})
            if not isinstance(rename, dict) or not set(rename) <= set(fields) or not all(isinstance(value, str) for value in rename.values()):
                raise JournalError(f"invalid projection rename for {event_type}")
            if projection.get("target") == "proposals" and projection.get("key") not in fields:
                raise JournalError(f"invalid projection key for {event_type}")
    views = manifest.get("views", {})
    if not isinstance(views, dict) or not set(views) <= {"daily", "weekly", "state"}:
        raise JournalError(f"invalid views in {reference}")
    for view_type in ("daily", "weekly", "state"):
        items = views.get(view_type, [])
        if not isinstance(items, list):
            raise JournalError(f"invalid {view_type} views in {reference}")
        for item in items:
            operation = item.get("operation", "value") if isinstance(item, dict) else None
            allowed = {"value"} if view_type != "weekly" else {"value", "sum", "count_truthy"}
            if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not isinstance(item.get("path"), str) or operation not in allowed:
                raise JournalError(f"invalid {view_type} view in {reference}")


def compile_registry(system_path: Path) -> tuple[dict[str, Any], CompiledRegistry]:
    try:
        system = json.loads(system_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JournalError(f"could not load system registry: {exc}") from exc
    if system.get("schema_version") != 1:
        raise JournalError("unsupported system registry schema")
    agents = system.get("agents", [])
    if not isinstance(agents, list):
        raise JournalError("system agents must be a list")
    agent_ids = {item.get("id") for item in agents if isinstance(item, dict)}
    if None in agent_ids or len(agent_ids) != len(agents):
        raise JournalError("system agent ids must be present and unique")
    if sum(item.get("coordinator") is True for item in agents) != 1:
        raise JournalError("system must define exactly one coordinator")
    configured_principals = system.get("principals", [])
    if not isinstance(configured_principals, list) or not all(isinstance(item, str) for item in configured_principals):
        raise JournalError("system principals must be a list of ids")
    principals = frozenset(set(configured_principals) | agent_ids)
    raw_resources = system.get("resources", {})
    if not isinstance(raw_resources, dict):
        raise JournalError("system resources must be a capability map")
    resources: dict[str, Mapping[str, tuple[str, ...]]] = {}
    for capability, rules in raw_resources.items():
        if not isinstance(capability, str) or not capability.startswith("resources.") or not isinstance(rules, dict):
            raise JournalError(f"invalid resource capability: {capability}")
        if not set(rules) <= {"read", "write"}:
            raise JournalError(f"invalid resource operations for {capability}")
        normalized: dict[str, tuple[str, ...]] = {}
        for operation, patterns in rules.items():
            if not isinstance(patterns, list) or not patterns or not all(isinstance(item, str) and item and not item.startswith("/") and ".." not in Path(item).parts for item in patterns):
                raise JournalError(f"invalid resource paths for {capability}")
            normalized[operation] = tuple(patterns)
        resources[capability] = normalized
    known_capabilities = {"events.publish", *resources}
    principal_capabilities = system.get("principal_capabilities", {})
    if not isinstance(principal_capabilities, dict) or not set(principal_capabilities) <= principals:
        raise JournalError("principal capabilities reference unknown principals")
    capabilities: dict[str, frozenset[str]] = {}
    for agent in agents:
        declared = agent.get("capabilities", [])
        if not isinstance(declared, list) or not all(isinstance(item, str) and item for item in declared):
            raise JournalError(f"invalid capabilities for {agent.get('id')}")
        if not set(declared) <= known_capabilities:
            raise JournalError(f"unknown capability for {agent.get('id')}: {sorted(set(declared) - known_capabilities)}")
        capabilities[str(agent["id"])] = frozenset(declared)
        toolsets = agent.get("toolsets", {})
        if not isinstance(toolsets, dict) or not all(
            isinstance(platform, str)
            and isinstance(names, list)
            and names
            and all(isinstance(name, str) and name for name in names)
            and len(names) == len(set(names))
            for platform, names in toolsets.items()
        ):
            raise JournalError(f"invalid toolsets for {agent.get('id')}")
    for principal in configured_principals:
        declared = principal_capabilities.get(principal, [])
        if not isinstance(declared, list) or not all(isinstance(item, str) and item for item in declared):
            raise JournalError(f"invalid capabilities for {principal}")
        if not set(declared) <= known_capabilities:
            raise JournalError(f"unknown capability for {principal}: {sorted(set(declared) - known_capabilities)}")
        capabilities[principal] = frozenset(declared)
    events: dict[str, Mapping[str, Any]] = {}
    domains: dict[str, Mapping[str, Any]] = {}
    views: dict[str, list[Mapping[str, Any]]] = {"daily": [], "weekly": [], "state": []}
    for reference in system.get("domains", []):
        if not isinstance(reference, str):
            raise JournalError("domain references must be paths")
        manifest_path = Path(reference)
        if not manifest_path.is_absolute():
            manifest_path = system_path.parent / manifest_path
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JournalError(f"could not load domain manifest {reference}: {exc}") from exc
        _validate_domain_manifest(manifest, reference, principals)
        domain_id = str(manifest["id"])
        if domain_id in domains:
            raise JournalError(f"duplicate domain id: {domain_id}")
        domains[domain_id] = manifest
        for event_type, definition in manifest.get("events", {}).items():
            if event_type in events:
                raise JournalError(f"duplicate event type: {event_type}")
            events[event_type] = definition
        for view_type in views:
            for item in manifest.get("views", {}).get(view_type, []):
                views[view_type].append(item)
    known_domains = set(domains)
    for agent in agents:
        references = agent.get("domains", [])
        if not isinstance(references, list) or not set(references) <= known_domains:
            unknown = sorted(set(references) - known_domains) if isinstance(references, list) else references
            raise JournalError(f"agent {agent.get('id')} references unknown domains: {unknown}")
    return system, CompiledRegistry(
        principals=principals,
        capabilities=capabilities,
        resources=resources,
        events=events,
        daily_views=tuple(views["daily"]),
        weekly_views=tuple(views["weekly"]),
        state_views=tuple(views["state"]),
        domains=domains,
    )


@dataclass(frozen=True)
class AuthenticatedEnvelope:
    """An event draft whose principal was bound by a registered Adapter."""

    adapter: "StaticPrincipalAdapter"
    principal: str
    event_type: str
    payload: Mapping[str, Any]
    occurred_at: str | None = None
    event_id: str | None = None
    operational_day: str | None = None
    _seal: object | None = field(default=None, repr=False, compare=False)


class StaticPrincipalAdapter:
    """Small local Adapter used by trusted profile integrations and tests."""

    def __init__(self, adapter_id: str, principals: Mapping[str, str]):
        if not adapter_id or not principals:
            raise JournalError("adapter id and principal bindings are required")
        self.adapter_id = adapter_id
        self._principals = dict(principals)
        self._seal = object()

    def envelope(
        self,
        credential: str,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        occurred_at: str | None = None,
        event_id: str | None = None,
        operational_day: str | None = None,
    ) -> AuthenticatedEnvelope:
        try:
            principal = self._principals[credential]
        except KeyError as exc:
            raise JournalError("adapter could not authenticate principal") from exc
        return AuthenticatedEnvelope(
            adapter=self,
            principal=principal,
            event_type=event_type,
            payload=dict(payload),
            occurred_at=occurred_at,
            event_id=event_id,
            operational_day=operational_day,
            _seal=self._seal,
        )


@dataclass(frozen=True)
class HandleOutcome:
    committed: bool
    event_id: str
    snapshot: Path


@dataclass(frozen=True)
class ApplyOutcome:
    applied: bool
    generation: str
    added_domains: tuple[str, ...]
    removed_domains: tuple[str, ...]
    added_agents: tuple[str, ...]
    removed_agents: tuple[str, ...]


class AvatarOS:
    """Deep runtime module for authenticated event handling and projections."""

    def __init__(
        self,
        root: Path,
        system: Mapping[str, Any],
        registry: CompiledRegistry,
        adapters: Sequence[StaticPrincipalAdapter],
    ):
        self.root = root
        self.system = dict(system)
        self.registry = registry
        self._adapters = tuple(adapters)

    @classmethod
    def open(
        cls,
        root: Path,
        system_path: Path,
        *,
        adapters: Sequence[StaticPrincipalAdapter],
    ) -> "AvatarOS":
        system, registry = compile_registry(system_path)
        for adapter in adapters:
            unknown = set(adapter._principals.values()) - registry.principals
            if unknown:
                raise JournalError(f"adapter binds unknown principals: {sorted(unknown)}")
        root.mkdir(parents=True, exist_ok=True)
        return cls(root.resolve(), system, registry, adapters)

    def handle(self, envelope: AuthenticatedEnvelope) -> HandleOutcome:
        if envelope.adapter not in self._adapters:
            raise JournalError("envelope came from an unregistered adapter")
        if envelope._seal is not envelope.adapter._seal:
            raise JournalError("envelope was not authenticated by its adapter")
        if envelope.principal not in envelope.adapter._principals.values():
            raise JournalError("adapter did not bind the envelope principal")
        if "events.publish" not in self.registry.capabilities.get(envelope.principal, frozenset()):
            raise JournalError(f"principal {envelope.principal} lacks events.publish capability")
        occurred = parse_time(envelope.occurred_at) if envelope.occurred_at else dt.datetime.now(ZONE)
        expected_day = operational_day(occurred)
        if envelope.operational_day is not None and envelope.operational_day != expected_day:
            raise JournalError("operational_day does not match occurred_at")
        event = {
            "schema_version": VERSION,
            "event_id": envelope.event_id or f"evt-{uuid.uuid4()}",
            "source": envelope.principal,
            "occurred_at": occurred.isoformat(),
            "operational_day": expected_day,
            "type": envelope.event_type,
            "payload": dict(envelope.payload),
        }
        committed = append_event(self.root, event, self.registry)
        snapshot = reconcile(self.root, self.registry)
        return HandleOutcome(committed=committed, event_id=event["event_id"], snapshot=snapshot)

    def apply(self, system_path: Path, *, mode: str = "plan") -> ApplyOutcome:
        if mode not in {"plan", "commit"}:
            raise JournalError("apply mode must be plan or commit")
        desired_system, desired = compile_registry(system_path)
        current_agents = {str(item["id"]) for item in self.system.get("agents", [])}
        desired_agents = {str(item["id"]) for item in desired_system.get("agents", [])}
        current_domains, desired_domains = set(self.registry.domains), set(desired.domains)
        encoded = json.dumps(
            {"system": desired_system, "domains": desired.domains},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        generation = hashlib.sha256(encoded).hexdigest()[:16]
        outcome = ApplyOutcome(
            applied=mode == "commit",
            generation=generation,
            added_domains=tuple(sorted(desired_domains - current_domains)),
            removed_domains=tuple(sorted(current_domains - desired_domains)),
            added_agents=tuple(sorted(desired_agents - current_agents)),
            removed_agents=tuple(sorted(current_agents - desired_agents)),
        )
        if mode == "plan":
            return outcome

        events_path = self.root / "journal/events.jsonl"
        existing_events = deduplicate(read_events(events_path, desired))
        project(existing_events, desired)

        registry_root = self.root / "registry"
        generations = registry_root / "generations"
        generations.mkdir(parents=True, exist_ok=True)
        target = generations / generation
        if not target.exists():
            stage = Path(tempfile.mkdtemp(prefix=".pending-", dir=generations))
            domain_refs = []
            manifest_hashes = {}
            for domain_id, manifest in desired.domains.items():
                relative = f"domains/{domain_id}.json"
                content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
                _write(stage / relative, content)
                domain_refs.append(relative)
                manifest_hashes[domain_id] = hashlib.sha256(content.encode()).hexdigest()
            active_system = dict(desired_system)
            active_system["domains"] = domain_refs
            _write(stage / "system.json", json.dumps(active_system, indent=2, sort_keys=True) + "\n")
            _write(stage / "lock.json", json.dumps({
                "schema_version": 1,
                "generation": generation,
                "agents": sorted(desired_agents),
                "domains": manifest_hashes,
            }, indent=2, sort_keys=True) + "\n")
            os.replace(stage, target)
        current = registry_root / "current"
        previous_target = os.readlink(current) if current.is_symlink() else None
        link = registry_root / f".current-{uuid.uuid4().hex}"
        link.symlink_to(target.relative_to(registry_root))
        os.replace(link, current)
        try:
            reconcile(self.root, desired)
        except Exception:
            if previous_target is None:
                current.unlink(missing_ok=True)
            else:
                rollback_link = registry_root / f".rollback-{uuid.uuid4().hex}"
                rollback_link.symlink_to(previous_target)
                os.replace(rollback_link, current)
            raise
        self.system, self.registry = desired_system, desired
        return outcome


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


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _validate_manifest_payload(kind: str, source: str, payload: Any, definition: Mapping[str, Any]) -> None:
    if source not in definition.get("publishers", []):
        raise JournalError(f"source {source!r} cannot publish {kind!r}")
    if not isinstance(payload, dict) or not payload:
        raise JournalError("payload must be a non-empty object")
    fields = definition.get("fields", {})
    unknown = set(payload) - set(fields)
    if unknown:
        raise JournalError(f"fields not allowed for {kind}: {sorted(unknown)}")
    missing = set(definition.get("required", [])) - set(payload)
    if missing:
        raise JournalError(f"missing fields for {kind}: {sorted(missing)}")
    for key, value in payload.items():
        spec = fields[key]
        expected = spec.get("type", "string")
        expected_types = [expected] if isinstance(expected, str) else expected
        if not any(_matches_type(value, item) for item in expected_types):
            raise JournalError(f"{key} has invalid type")
        if isinstance(value, float) and not math.isfinite(value):
            raise JournalError(f"{key} must be finite")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                raise JournalError(f"{key} must be at least {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                raise JournalError(f"{key} must be at most {spec['maximum']}")
        if isinstance(value, str) and len(value) > spec.get("max_length", 500):
            raise JournalError(f"{key} is too long")


def validate_event(raw: dict[str, Any], registry: CompiledRegistry | None = None) -> dict[str, Any]:
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
    definition = registry.events.get(kind) if registry else None
    if registry is not None and definition is None:
        raise JournalError(f"unknown event type: {kind!r}")
    if registry is None and (source not in SOURCES or kind not in SOURCE_TYPES[source]):
        raise JournalError(f"source {source!r} cannot publish {kind!r}")
    occurred = parse_time(raw["occurred_at"])
    try:
        dt.date.fromisoformat(raw["operational_day"])
    except (TypeError, ValueError) as exc:
        raise JournalError("operational_day must be YYYY-MM-DD") from exc
    payload = raw["payload"]
    if definition is not None:
        _validate_manifest_payload(kind, source, payload, definition)
        clean = dict(raw)
        clean["schema_version"] = VERSION
        clean["occurred_at"] = occurred.isoformat()
        return clean
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


def append_event(root: Path, event: dict[str, Any], registry: CompiledRegistry | None = None) -> bool:
    event = validate_event(event, registry)
    path = root / "journal" / "events.jsonl"
    with locked(root):
        existing = {item["event_id"]: item for item in read_events(path, registry)}
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


def read_events(path: Path, registry: CompiledRegistry | None = None) -> list[dict[str, Any]]:
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
                events.append(validate_event(raw, registry))
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


def _merge_projection(target: dict[str, Any], payload: Mapping[str, Any], rule: Mapping[str, Any]) -> None:
    values = dict(payload)
    rename = rule.get("rename", {})
    values = {rename.get(key, key): value for key, value in values.items()}
    namespace = rule.get("namespace")
    if namespace:
        nested = target.setdefault(namespace, {})
        if not isinstance(nested, dict):
            raise JournalError(f"projection namespace collision: {namespace}")
        nested.update(values)
    else:
        target.update(values)


def project(events: list[dict[str, Any]], registry: CompiledRegistry | None = None) -> dict[str, Any]:
    daily: dict[str, dict[str, Any]] = defaultdict(dict)
    proposals: dict[str, dict[str, Any]] = {}
    runs = []
    state: dict[str, Any] = {}
    for event in events:
        kind, payload, day = event["type"], event["payload"], event["operational_day"]
        definition = registry.events.get(kind) if registry else None
        if definition is not None:
            for rule in definition.get("projections", []):
                operation, target = rule.get("operation"), rule.get("target")
                if operation == "merge" and target in {"daily", "state"}:
                    _merge_projection(daily[day] if target == "daily" else state, payload, rule)
                elif operation == "upsert" and target == "proposals":
                    key = str(payload[rule["key"]])
                    proposals[key] = dict(payload)
                elif operation == "merge" and target == "proposals":
                    key = str(payload[rule["key"]])
                    proposals.setdefault(key, {rule["key"]: key}).update(payload)
                elif operation == "append" and target == "runs":
                    runs.append({"occurred_at": event["occurred_at"], **payload})
                else:
                    raise JournalError(f"unsupported projection for {kind}: {operation} -> {target}")
            continue
        if kind in {"daily_log", "gate_log", "health_log", "readiness", "effort_score"}:
            daily[day].update(payload)
        if kind == "review_proposal":
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


def _lookup(values: Mapping[str, Any], path: str) -> Any:
    current: Any = values
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def daily_markdown(day: str, values: dict[str, Any], registry: CompiledRegistry | None = None) -> str:
    lines = [f"# AVATAR DAILY — {day}", "", "Generated from the event journal. Do not edit directly.", "", "## Log", ""]
    if registry is None:
        labels = [
            ("GATE", "gate_minutes"), ("GATE topic", "gate_topic"), ("Gym", "gym"),
            ("DSA", "dsa"), ("Fruit", "fruit"), ("Protein hits", "protein_hits"),
            ("Sleep", "sleep"), ("Wake", "wake"), ("Energy (1–10)", "energy"),
            ("Stress (1–10)", "stress"), ("Soreness/pain/illness", "soreness"),
            ("Readiness", "readiness"), ("Deviations", "deviation"),
        ]
        lines.extend(f"- {label}: {_display(values.get(key))}" for label, key in labels)
    else:
        for view in registry.daily_views:
            value = _display(_lookup(values, str(view["path"])))
            suffix = str(view.get("suffix", "")) if value != "Not logged" else ""
            lines.append(f"- {view['label']}: {value}{suffix}")
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


def weekly_markdown(week: str, rows: list[dict[str, Any]], registry: CompiledRegistry | None = None) -> str:
    numeric = lambda key: sum(float(row.get(key, 0)) for row in rows if isinstance(row.get(key), (int, float)))
    yes = lambda key: sum(str(row.get(key, "")).lower() in {"yes", "done", "completed", "a", "b"} for row in rows)
    lines = [f"# AVATAR WEEK — {week}", "", "Generated from the event journal. Do not edit directly.", "", "## Actuals", ""]
    if registry is None:
        lines.extend([f"- GATE minutes: {numeric('gate_minutes'):g}", f"- Gym sessions: {yes('gym')}", f"- DSA days: {yes('dsa')}", f"- Fruit days: {yes('fruit')}", f"- Protein hits: {numeric('protein_hits'):g}"])
    else:
        for view in registry.weekly_views:
            values = [_lookup(row, str(view["path"])) for row in rows]
            operation = view.get("operation")
            if operation == "sum":
                result = sum(float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool))
                rendered = f"{result:g}"
            elif operation == "count_truthy":
                rendered = str(sum(bool(value) for value in values))
            else:
                raise JournalError(f"unsupported weekly view operation: {operation}")
            lines.append(f"- {view['label']}: {rendered}{view.get('suffix', '')}")
    lines.append("")
    return "\n".join(lines)


def state_markdown(state: dict[str, Any], registry: CompiledRegistry | None = None) -> str:
    lines = ["# AVATAR STATE", "", "Generated from the event journal. Do not edit directly.", ""]
    if registry is None:
        lines.extend([f"- Mode: {_display(state.get('mode'))}", f"- NEXT GATE: {_display(state.get('next_gate', state.get('next_action')))}", f"- NEXT FITNESS: {_display(state.get('next_fitness', state.get('constraint')))}", f"- NEXT DSA: {_display(state.get('next_dsa'))}", f"- Readiness: {_display(state.get('readiness'))}"])
    else:
        lines.extend(f"- {view['label']}: {_display(_lookup(state, str(view['path'])))}" for view in registry.state_views)
    lines.append("")
    return "\n".join(lines)


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
    with path.open(mode, **kwargs) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def reconcile(root: Path, registry: CompiledRegistry | None = None) -> Path:
    with locked(root):
        journal = root / "journal"
        events_path = journal / "events.jsonl"
        raw_bytes = events_path.read_bytes() if events_path.exists() else b""
        events = deduplicate(read_events(events_path, registry))
        projection = project(events, registry)
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
            _write(stage / "daily" / f"{day}.md", daily_markdown(day, values, registry))
        weeks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for day, values in projection["daily"].items():
            date = dt.date.fromisoformat(day)
            week = (date - dt.timedelta(days=date.weekday())).isoformat()
            weeks[week].append(values)
        for week, rows in weeks.items():
            _write(stage / "weekly" / f"{week}.md", weekly_markdown(week, rows, registry))
        _write(stage / "STATE.md", state_markdown(projection["state"], registry))
        _write(stage / "SHARED_CONTEXT.md", state_markdown(projection["state"], registry).replace("# AVATAR STATE", "# SHARED CONTEXT", 1))
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
    result.add_argument("--system", type=Path)
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
        system_path = args.system.resolve() if args.system else root / "registry/system.json"
        registry = compile_registry(system_path)[1] if system_path.is_file() else None
        if args.command == "append":
            created = append_event(root, make_event(args), registry)
            print("appended" if created else "duplicate ignored")
        elif args.command in {"reconcile", "rebuild"}:
            print(reconcile(root, registry))
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
