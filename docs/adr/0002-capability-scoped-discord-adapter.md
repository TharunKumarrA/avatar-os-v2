---
status: accepted
---

# Use capability-scoped tools for Discord state access

Discord Agents access Avatar OS state through the authenticated `avatar-os`
Hermes toolset. The Registry grants independent Event publication and
resource-path capabilities to each Principal. Generic file access is excluded
from Discord sessions; CLI administration remains a trusted operator surface.

## Consequences

An Agent being listed as an Event publisher is insufficient without the
`events.publish` capability. Shared reads and writes are constrained by
Registry path patterns, resolved beneath the shared-state root, and written
atomically. Toph, Sokka, and Iroh cannot write coordination state or another
Agent's handoff. Adding a new Agent requires explicit capabilities and Discord
toolsets, and repository validation rejects configuration drift.
