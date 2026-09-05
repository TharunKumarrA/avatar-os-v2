---
status: accepted
---

# Use a declarative registry behind a deep runtime interface

Avatar OS uses versioned declarative Domain manifests compiled into immutable
Registry Generations and exposes lifecycle and event handling through the small
`AvatarOS.open`, `apply`, and `handle` interface. This keeps Hermes and Discord
as Adapters, lets Domains evolve independently of Agents, and avoids both the
previous scattered hardcoded model and a premature executable plugin framework.

## Consequences

Human-authored plans and role policies remain ordinary documents. Mechanical
schemas, projections, permissions, routing, and lifecycle declarations belong
in the Registry. Executable Package extensions are out of scope until at least
two real Domains cannot be expressed by the supported declarative operations.
