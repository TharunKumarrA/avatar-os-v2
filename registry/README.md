# Registry guide

The registry is Avatar OS's desired configuration. `system.json` composes
Agents and Domains; each file in `domains/` defines one bounded subject area.

## Add a Domain

1. Run `python3 scripts/scaffold.py domain NAME --owner AGENT --plan`, inspect
   the plan, then repeat with `--apply`.
2. Define versioned Events, their authorised publishers, typed fields, and the
   supported declarative projections.
3. Add the manifest path to `system.json` and assign its id to the relevant
   Agents. A Domain does not require a new Agent.
4. Run `python3 scripts/validate.py` and the test suite.
5. Preview it through `AvatarOS.apply(..., mode="plan")`; activate only after
   reviewing the reported additions and removals.

An active Domain may supply `daily_close_prompt`. The workflow compiler adds
that bounded question to Katara's generated close; the Domain cannot modify the
workflow's safety and delivery instructions.

## Add an Agent

1. Run `python3 scripts/scaffold.py agent NAME --domains DOMAIN --plan`, inspect
   the plan, then repeat with `--apply`.
2. Complete the generated role/profile details and explicitly choose any write
   capability. New Agents receive event publishing and shared reads only.
3. Run `python3 scripts/render_profiles.py`, validation, and an installer dry
   run. Exactly one Agent must be the coordinator.

Agents are identities and authority boundaries. Domains are reusable behaviour.
Prefer adding a Domain to an existing Agent unless a distinct Discord identity,
conversation boundary, or permission boundary is actually needed.

The compiler accepts only known field types, projection operations, and View
aggregations. This is deliberate: packages remain data that can be reviewed and
validated rather than arbitrary executable plugins.
