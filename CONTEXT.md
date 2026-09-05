# Avatar OS

Avatar OS coordinates independent conversational actors, personal domains, and
durable facts without making the user manage the coordination machinery.

## Language

**Agent**:
A deployed conversational identity with delegated authority, policy, and routing.
_Avoid_: Bot, persona, specialist when referring to the deployed identity

**Domain**:
A subject area that owns a vocabulary, rules, Events, and Views, such as fitness
or reading. A Domain does not imply a separate Agent.
_Avoid_: Agent, feature area

**Capability**:
An enforceable permission for a Principal to perform a bounded action on a
named resource.
_Avoid_: Tool, role instruction

**Feature**:
Optional user-visible behavior contributed within one or more Domains, without
identity or authority of its own.
_Avoid_: Agent, plugin

**Workflow**:
A triggered sequence of capability-scoped actions with an owner and a defined
failure policy.
_Avoid_: Cron job when referring to behavior rather than its trigger

**Event**:
An immutable, versioned observation or decision accepted from an authenticated
Principal.
_Avoid_: Message, handoff, log line

**View**:
A deterministic human- or machine-readable projection of Events.
_Avoid_: Source of truth, editable report

**Principal**:
The authenticated identity on whose authority an Event or management action is
performed.
_Avoid_: Caller-supplied source

**Adapter**:
A concrete integration that authenticates a Principal or connects Avatar OS to
Hermes, Discord, storage, or another external system.
_Avoid_: Domain logic, agent

**Package**:
A versioned deployable bundle that contributes Domain, Agent, Feature, or
Workflow definitions.
_Avoid_: Unversioned prompt folder

**Registry**:
The validated desired description of active Packages, Agents, Domains,
Capabilities, Workflows, and Adapters.
_Avoid_: Scattered configuration lists

**Generation**:
An immutable, content-addressed compiled Registry that can be activated or
replaced atomically.
_Avoid_: Mutable live configuration
