# KATARA OS v1

Avatar OS uses four independent Discord bots and Hermes profiles over a shared
source of truth. It tracks weekly quotas, interprets short manual logs, protects
recovery, and always returns one meaningful next action.

## Agents

- **Katara** — Navigator, priorities, logging, schedule, and next action
- **Toph** — GATE Tutor, PYQs, testing, revision, and error diagnosis
- **Sokka** — Health Coach, workouts, food, sleep, and readiness
- **Iroh** — Reviewer, weekly totals, patterns, and one adjustment proposal

## Discord channel map

- `#avatar-hub`: mention `@Katara` for navigation or `@Iroh` for review.
- `#study`: Toph answers naturally; no mention is required.
- `#health-metrics`: Sokka answers naturally; no mention is required.
- `#service`: Katara handles status, restart, session, and error questions;
  no mention is required.
- `#general`: not part of Avatar OS.

Send natural messages; strict commands are unnecessary.

Examples:

```text
Green day. Gym A done. GATE 82m — OS scheduling. Fruit yes. Protein 3.
Energy 7/10. Slept 1:50, woke 9:05.
```

```text
Yellow today. Poor sleep. Do I train?
```

```text
@Katara status
@Katara what is next?
@Iroh review this week
```

Katara should acknowledge what was recorded, show progress only when useful,
and end with exactly one next action.

Specialist examples:

```text
In #study: teach me CPU scheduling.
In #study: test me on deadlocks.
In #health-metrics: energy 4/10 and slept five hours; should I train?
In #avatar-hub: @Iroh review this week.
```

## Files

- `PROFILE.md`: canonical shared identity, goals, preferences, and boundaries
- `SHARED_CONTEXT.md`: Katara-owned compact live snapshot for every agent
- `PLAN.md`: durable rules, quotas, schedule, workouts, and food plan
- `STATE.md`: active week, A/B rotation, and one next action per domain
- `daily/`: observations; never assumptions
- `weekly/`: quotas, totals, review, and one adjustment
- `handoffs/`: current specialist updates that Katara reconciles
- `gate/`: diagnostic, topic-note format, and error log
- `AGENT_CONTRACTS.md`: ownership, routing, and write boundaries
- `REVIEW_QUEUE.md`: Iroh's single proposal awaiting Tharun's decision

## Daily rhythm

1. Morning: log Green, Yellow, or Red plus any sleep/energy information.
2. During the day: send short completion or deviation messages.
3. At 01:15: close the day in under 30 seconds.
4. Sunday: Iroh answers the five review questions and proposes one adjustment.
5. Katara applies it only after you accept, modify, or reject it.

## Shared context

The four bots keep separate conversations. They coordinate through files rather
than by copying chats or messaging one another. Specialists write concise
domain handoffs; Katara reads them before every cross-domain decision and
updates the shared snapshot. Files outrank conversational memory when they
conflict.

## Non-negotiable recovery rule

Never repay missed work. Never double tomorrow. Resume at the minimum viable
version or the next normal block.
