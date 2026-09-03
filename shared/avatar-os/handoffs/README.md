# AVATAR OS — HANDOFF PROTOCOL

Each specialist owns exactly one handoff file. A handoff is a current structured
snapshot, not a chat transcript and not a second scoreboard.

## Ownership

- Toph writes only `toph.md`.
- Sokka writes only `sokka.md`.
- Iroh writes only `iroh.md`.
- Katara reads all handoffs and writes `../SHARED_CONTEXT.md`.

## Required behavior

After a meaningful interaction, the specialist immediately updates its handoff
when the interaction contains any of the following:

- an explicit completion or deviation;
- a new constraint, blocker, readiness label, or demonstrated weakness;
- a changed domain next action;
- a recommendation that affects another domain;
- a review proposal or decision needed from Tharun.

Use an Asia/Kolkata timestamp. Preserve only current, explicit, decision-useful
facts. Never copy private conversational detail, speculation, or an entire
response. Unknown remains `Unknown`.

Katara reads every handoff before a status, `what next?`, morning brief, nightly
close, or cross-domain decision. Katara reconciles newer evidence into the
canonical daily file, `STATE.md`, weekly actuals, and `SHARED_CONTEXT.md` without
double-counting.

Other specialists read `SHARED_CONTEXT.md` first. They read another specialist's
handoff only when a cross-domain constraint is directly relevant. For example,
Toph may use Sokka's readiness label and safe study-dose constraint, but should
not repeat detailed health information.

