"""Hermes plugin that records events through Avatar OS's authenticated interface."""

from __future__ import annotations

import importlib.util
import fnmatch
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = {
    "name": "avatar_os_record",
    "description": (
        "Record one explicit user observation or agent result in Avatar OS. "
        "Use only an event type allowed for this active Hermes profile. "
        "Identity and operational date are assigned by the adapter."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "description": "Registered Avatar OS event type.",
            },
            "payload": {
                "type": "object",
                "description": "Typed event fields containing only explicit facts.",
            },
            "occurred_at": {
                "type": "string",
                "description": "Optional ISO-8601 timestamp with UTC offset.",
            },
            "event_id": {
                "type": "string",
                "description": "Optional stable idempotency identifier.",
            },
        },
        "required": ["event_type", "payload"],
        "additionalProperties": False,
    },
}

RESOURCE_SCHEMA = {
    "name": "avatar_os_resource",
    "description": (
        "Read or write an Avatar OS shared-state resource when the active "
        "Hermes profile has the required registry capability."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["read", "write"]},
            "path": {"type": "string", "description": "Path relative to Avatar OS shared state."},
            "content": {"type": "string", "description": "Complete file content required for write."},
        },
        "required": ["operation", "path"],
        "additionalProperties": False,
    },
}


def _state_root() -> Path:
    configured = os.environ.get("AVATAR_OS_STATE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        from hermes_constants import get_hermes_home
        home = Path(get_hermes_home()).expanduser().resolve()
    except ImportError:
        home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()
    base = home.parent.parent if home.parent.name == "profiles" else home
    return base / "katara"


def _load_runtime(state_root: Path):
    runtime_path = state_root / "tools/avatar_os.py"
    module_name = "avatar_os_installed_runtime"
    spec = importlib.util.spec_from_file_location(module_name, runtime_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Avatar OS runtime is unavailable at {runtime_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _principal(profile_name: str | None, system: dict[str, Any]) -> str:
    value = (profile_name or "").strip().lower()
    if value and value != "default":
        return value
    coordinators = [str(item["id"]) for item in system["agents"] if item.get("coordinator") is True]
    if len(coordinators) != 1:
        raise RuntimeError("Avatar OS registry must define exactly one coordinator")
    return coordinators[0]


def _resource_target(state_root: Path, system: dict[str, Any], principal: str, operation: str, raw_path: str) -> Path:
    if operation not in {"read", "write"}:
        raise ValueError("resource operation must be read or write")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("resource path must stay inside Avatar OS shared state")
    agents = {str(item["id"]): item for item in system["agents"]}
    capabilities = agents.get(principal, {}).get("capabilities")
    if capabilities is None:
        capabilities = system.get("principal_capabilities", {}).get(principal, [])
    normalized = relative.as_posix()
    allowed = any(
        fnmatch.fnmatchcase(normalized, pattern)
        for capability in capabilities
        for pattern in system.get("resources", {}).get(capability, {}).get(operation, [])
    )
    if not allowed:
        raise PermissionError(f"principal {principal} cannot {operation} resource {normalized}")
    root = state_root.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise PermissionError("resource path escapes Avatar OS shared state")
    return target


def register(ctx) -> None:
    """Register a profile-bound event recording tool."""
    def handle(args: dict[str, Any], **_kwargs: Any) -> str:
        try:
            allowed = {"event_type", "payload", "occurred_at", "event_id"}
            unknown = set(args) - allowed
            if unknown:
                raise ValueError(f"unsupported arguments: {sorted(unknown)}")
            state_root = _state_root()
            system_path = state_root / "registry/system.json"
            system = json.loads(system_path.read_text(encoding="utf-8"))
            principal = _principal(ctx.profile_name, system)
            runtime_module = _load_runtime(state_root)
            adapter = runtime_module.StaticPrincipalAdapter(
                f"hermes:{principal}", {"active-profile": principal},
            )
            runtime = runtime_module.AvatarOS.open(
                state_root, system_path, adapters=[adapter],
            )
            envelope = adapter.envelope(
                "active-profile",
                event_type=str(args["event_type"]),
                payload=args["payload"],
                occurred_at=args.get("occurred_at"),
                event_id=args.get("event_id"),
            )
            outcome = runtime.handle(envelope)
            return json.dumps({
                "success": True,
                "status": "recorded" if outcome.committed else "duplicate",
                "event_id": outcome.event_id,
                "snapshot": str(outcome.snapshot),
            })
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    def resource(args: dict[str, Any], **_kwargs: Any) -> str:
        try:
            unknown = set(args) - {"operation", "path", "content"}
            if unknown:
                raise ValueError(f"unsupported arguments: {sorted(unknown)}")
            operation = str(args["operation"])
            state_root = _state_root()
            system = json.loads((state_root / "registry/system.json").read_text(encoding="utf-8"))
            principal = _principal(ctx.profile_name, system)
            target = _resource_target(state_root, system, principal, operation, str(args["path"]))
            if operation == "read":
                content = target.read_text(encoding="utf-8")
                if len(content) > 131072:
                    raise ValueError("resource exceeds 128 KiB read limit")
                return json.dumps({"success": True, "path": str(args["path"]), "content": content})
            if "content" not in args:
                raise ValueError("content is required for resource writes")
            content = str(args["content"])
            if len(content.encode()) > 131072:
                raise ValueError("resource exceeds 128 KiB write limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, pending = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(pending, target)
            finally:
                if os.path.exists(pending):
                    os.unlink(pending)
            return json.dumps({"success": True, "path": str(args["path"]), "status": "written"})
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    ctx.register_tool(
        name="avatar_os_record",
        toolset="avatar-os",
        schema=SCHEMA,
        handler=handle,
        emoji="🌊",
    )
    ctx.register_tool(
        name="avatar_os_resource",
        toolset="avatar-os",
        schema=RESOURCE_SCHEMA,
        handler=resource,
        emoji="📘",
    )
